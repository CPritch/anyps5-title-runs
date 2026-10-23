"""The pull requests of a repository, as a GraphQL listing kept on disk (the All pull requests page), read with the
tester's sign-in.

The first refresh lists every open PR; later ones list PRs of every state by updatedAt, newest first, only back to the
newest one already cached, so a refresh costs a page or two. Every query asks for rateLimit, and a query is refused
once the remaining budget is below the reserve, so the listing never spends what the tester's other tools need.
"""

import datetime
import json
import os
import urllib.request
from pathlib import Path

from .formats import parse_time

API = "https://api.github.com"

FIELDS = """number title url state isDraft updatedAt mergeable baseRefName headRefName headRefOid
author { login }
labels(first: 20) { nodes { name } }
body
commits(last: 1) { nodes { commit { oid committedDate author { user { login } } } } }"""

LISTING = """query($owner: String!, $name: String!, $after: String, $states: [PullRequestState!]) {
  rateLimit { remaining cost resetAt }
  repository(owner: $owner, name: $name) {
    pullRequests(first: 50, after: $after, states: $states, orderBy: {field: UPDATED_AT, direction: DESC}) {
      pageInfo { hasNextPage endCursor }
      nodes { %s }
    }
  }
}""" % FIELDS

OVERLAP = datetime.timedelta(minutes=2)


class BudgetExhausted(RuntimeError):
    pass


class GraphQL:
    """GitHub's GraphQL API with a token from token(), a callable (the tester's sign-in)."""

    def __init__(self, token, reserve=200):
        self.token, self.reserve = token, reserve
        self.remaining = None
        self.reset_at = None
        self.spent = 0

    def _post(self, payload):
        token = self.token()
        if not token:
            raise RuntimeError("not signed in")
        request = urllib.request.Request(f"{API}/graphql", data=json.dumps(payload).encode(), method="POST",
                                         headers={"Authorization": f"bearer {token}", "Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read())

    def query(self, query, variables=None):
        if self.remaining is not None and self.remaining < self.reserve:
            raise BudgetExhausted(f"GraphQL budget {self.remaining} is below the reserve {self.reserve} (resets {self.reset_at})")
        reply = self._post({"query": query, "variables": variables or {}})
        if reply.get("errors"):
            raise RuntimeError(f"GraphQL errors: {json.dumps(reply['errors'])[:500]}")
        data = reply["data"]
        limit = data.get("rateLimit") or {}
        if limit:
            self.remaining, self.reset_at = limit.get("remaining"), limit.get("resetAt")
            self.spent += limit.get("cost", 0)
        return data


class Listing:
    def __init__(self, path, repository=None):
        self.path = Path(path)
        self.data = json.loads(self.path.read_text()) if self.path.exists() else {"newest": None, "prs": {}}
        if repository:
            self.data.setdefault("repository", repository)

    @classmethod
    def of(cls, state_dir, repository):
        """The listing of one repository (OWNER/NAME) in the state directory's cache."""
        return cls(Path(state_dir) / "cache" / f"pull-requests-{repository.replace('/', '-')}.json", repository)

    def refreshed(self):
        """When the listing was last brought up to date (ISO), or None."""
        return self.data.get("refreshed")

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.data))
        os.replace(temporary, self.path)

    def merge(self, nodes):
        for node in nodes:
            if node:
                self.data["prs"][str(node["number"])] = node
                if not self.data["newest"] or parse_time(node["updatedAt"]) > parse_time(self.data["newest"]):
                    self.data["newest"] = node["updatedAt"]

    def refresh(self, client, owner, name, max_pages=None):
        """Bring the listing up to date; returns the number of pages read. Records the repository and the time."""
        self.data["repository"] = f"{owner}/{name}"
        self.data["refreshed"] = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        first = not self.data["prs"]
        stop = None if first else parse_time(self.data["newest"]) - OVERLAP
        after, pages = None, 0
        while True:
            variables = {"owner": owner, "name": name, "after": after, "states": ["OPEN"] if first else None}
            page = client.query(LISTING, variables)["repository"]["pullRequests"]
            pages += 1
            nodes = page["nodes"]
            self.merge(nodes)
            reached = stop is not None and nodes and parse_time(nodes[-1]["updatedAt"]) < stop
            if reached or not page["pageInfo"]["hasNextPage"] or (max_pages and pages >= max_pages):
                break
            after = page["pageInfo"]["endCursor"]
        self.save()
        return pages

    def get(self, number):
        return self.data["prs"].get(str(number))

    def open(self):
        return [pr for pr in self.data["prs"].values() if pr.get("state") == "OPEN"]
