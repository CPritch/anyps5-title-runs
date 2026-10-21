"""Poll GitHub for new heads of followed pull requests.

The listing is a GraphQL listing kept on disk, as upstream-status.py does for the harness: the first poll lists every
open PR; later polls list PRs of every state by updatedAt, newest first, only back to the newest one already cached,
so a poll costs a page or two. Explicitly followed PRs are also read directly every poll (one query with aliases), so
their heads are fresh even when the listing is behind.

A new head is not built at once: it must stay unchanged for debounce_minutes (a push often comes in several parts), and
a head that is replaced before it was built is marked superseded and never built.
"""

import datetime
import json
import os
from pathlib import Path

from . import rules
from .state import DONE, FAILED, PAUSED, READY, RUNNING, SUPERSEDED, WAITING, iso, now, parse

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


def direct_query(numbers):
    aliases = "\n".join(f"pr{number}: pullRequest(number: {int(number)}) {{ {FIELDS} }}" for number in numbers)
    return "query($owner: String!, $name: String!) { rateLimit { remaining cost resetAt } repository(owner: $owner, name: $name) { %s } }" % aliases


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
                if not self.data["newest"] or parse(node["updatedAt"]) > parse(self.data["newest"]):
                    self.data["newest"] = node["updatedAt"]

    def refresh(self, client, owner, name, max_pages=None):
        """Bring the listing up to date; returns the number of pages read. Records the repository and the time."""
        self.data["repository"] = f"{owner}/{name}"
        self.data["refreshed"] = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        first = not self.data["prs"]
        stop = None if first else parse(self.data["newest"]) - OVERLAP
        after, pages = None, 0
        while True:
            variables = {"owner": owner, "name": name, "after": after, "states": ["OPEN"] if first else None}
            page = client.query(LISTING, variables)["repository"]["pullRequests"]
            pages += 1
            nodes = page["nodes"]
            self.merge(nodes)
            reached = stop is not None and nodes and parse(nodes[-1]["updatedAt"]) < stop
            if reached or not page["pageInfo"]["hasNextPage"] or (max_pages and pages >= max_pages):
                break
            after = page["pageInfo"]["endCursor"]
        self.save()
        return pages

    def fetch(self, client, owner, name, numbers):
        if not numbers:
            return
        repository = client.query(direct_query(numbers), {"owner": owner, "name": name})["repository"]
        self.merge(repository.values())
        self.save()

    def get(self, number):
        return self.data["prs"].get(str(number))

    def open(self):
        return [pr for pr in self.data["prs"].values() if pr.get("state") == "OPEN"]


def first_seen(pr, moment):
    """When a newly followed head counts as seen: now, or its commit date when that is earlier (the head has
    then been unchanged at least that long, unless an older commit was pushed again)."""
    nodes = (pr.get("commits") or {}).get("nodes") or []
    committed = parse(nodes[-1]["commit"].get("committedDate")) if nodes and nodes[-1].get("commit") else None
    return min(moment, committed) if committed else moment


def update(state, listing, config, moment=None):
    """Apply one poll to the state. Returns events: (pr, kind, detail) with kind new-head, superseded, ready, paused,
    unfollowed."""
    moment = moment or now()
    debounce = datetime.timedelta(minutes=config.debounce_minutes)
    events = []
    candidates = {pr["number"]: pr for pr in listing.open()}
    for number in config.follow_prs:
        pr = listing.get(number)
        if pr:
            candidates[number] = pr
    for number, entry in state.prs().items():
        if number not in candidates and listing.get(number):
            candidates[number] = listing.get(number)
    for number, pr in sorted(candidates.items()):
        reason = rules.followed(pr, config)
        entry = state.data["prs"].get(str(number))
        if reason is None:
            if entry and entry.get("followed"):
                entry["followed"] = None
                events.append((number, "unfollowed", pr.get("state", "")))
            continue
        entry = state.pr(number)
        entry.update({"followed": reason, "title": pr.get("title", ""), "author": (pr.get("author") or {}).get("login"), "url": pr.get("url", "")})
        head = state.current(number)
        if head is None or head["head"] != pr["headRefOid"]:
            if head is not None and head["status"] in (WAITING, PAUSED, READY):
                head["status"] = SUPERSEDED
                head["superseded_at"] = iso(moment)
                events.append((number, "superseded", head["head"]))
            seen = first_seen(pr, moment) if head is None else moment
            entry["heads"].append({"head": pr["headRefOid"], "seen": iso(seen), "status": WAITING, "base_ref": pr.get("baseRefName")})
            events.append((number, "new-head", pr["headRefOid"]))
            head = entry["heads"][-1]
        if head["status"] == WAITING and moment - parse(head["seen"]) >= debounce:
            ok, why = rules.trusted(pr, config)
            if ok or head["head"] in entry.get("confirmed", []):
                head["status"] = READY
                head["trust"] = why if ok else "confirmed by the tester"
                events.append((number, "ready", head["head"]))
            else:
                head["status"] = PAUSED
                head["trust"] = why
                events.append((number, "paused", why))
    return events


def confirm(state, number, head=None):
    entry = state.pr(number)
    current = state.current(number)
    if current is None:
        raise ValueError(f"#{number} has no head to confirm")
    head = head or current["head"]
    entry.setdefault("confirmed", []).append(head)
    if current["head"] == head and current["status"] == PAUSED:
        current["status"] = READY
        current["trust"] = "confirmed by the tester"
    return current


def ready(state):
    return [(number, state.current(number)) for number in sorted(state.prs()) if state.current(number) and state.current(number)["status"] == READY]


def finish(state, number, head, status, job):
    for entry in state.pr(number)["heads"]:
        if entry["head"] == head:
            entry["status"] = status
            entry["job"] = str(job) if job else None
            entry["finished"] = iso(now())
    return state


__all__ = ["Listing", "update", "confirm", "ready", "finish", "DONE", "FAILED", "RUNNING"]
