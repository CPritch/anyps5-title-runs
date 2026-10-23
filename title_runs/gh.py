"""GitHub's REST API, read only and without a sign-in: a project's open pull requests (listing.py), a pull request's head
and state, the workflow runs that tell who pushed a head, and a person's open pull requests (local_tests.py). Nothing
here writes to GitHub. Without a sign-in GitHub allows 60 requests an hour per IP address, and 10 a minute for its
search; RateLimited says until when when they're used up."""

import datetime
import json
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.github.com"


class GitHubError(RuntimeError):
    pass


class RateLimited(GitHubError):
    """GitHub's limit is used up until reset (a UTC datetime): 60 requests an hour for the API without a sign-in, 10 a
    minute for its search."""

    def __init__(self, message, reset):
        super().__init__(message)
        self.reset = reset


def limited(error, now=None):
    """The RateLimited an HTTPError is, or None: a 403 or 429 with no requests left, or with Retry-After."""
    if error.code not in (403, 429):
        return None
    headers = error.headers or {}
    now = now or datetime.datetime.now(datetime.timezone.utc)
    if headers.get("Retry-After"):
        reset = now + datetime.timedelta(seconds=int(headers["Retry-After"]))
    elif headers.get("X-RateLimit-Remaining") == "0" and headers.get("X-RateLimit-Reset"):
        reset = datetime.datetime.fromtimestamp(int(headers["X-RateLimit-Reset"]), datetime.timezone.utc)
    else:
        return None
    return RateLimited(f"GitHub's limit is used up until {reset:%H:%M} UTC", reset)


class GitHubRepo:
    """One repository, read without a sign-in."""

    def __init__(self, repository):
        self.repository = repository

    def call(self, path, params=None):
        url = f"{API}{path}" + (f"?{urllib.parse.urlencode(params)}" if params else "")
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60) as response:
                return json.loads(response.read() or b"null")
        except urllib.error.HTTPError as error:
            raise limited(error) or GitHubError(f"GET {path}: HTTP {error.code} {error.read()[:300]!r}") from error

    def pages(self, path, params=None, limit=10):
        out = []
        for page in range(1, limit + 1):
            batch = self.call(path, params={**(params or {}), "per_page": 100, "page": page})
            items = batch.get("workflow_runs", []) if isinstance(batch, dict) else batch
            out += items
            if len(items) < 100:
                break
        return out

    def pull(self, number):
        """{"number", "title", "author", "head", "head_ref", "state" (open, closed or merged), "labels"}."""
        data = self.call(f"/repos/{self.repository}/pulls/{number}")
        return {"number": number, "title": data["title"], "author": data["user"]["login"], "head": data["head"]["sha"],
                "head_ref": data["head"]["ref"], "state": "merged" if data.get("merged_at") else data["state"],
                "labels": [label["name"] for label in data.get("labels", [])]}

    def open_pulls_by(self, login):
        """The open pull requests login opened, from GitHub's search: [{"number", "title", "author", "draft"}]."""
        query = f"repo:{self.repository} is:pr is:open author:{login}"
        items = self.call("/search/issues", {"q": query, "per_page": 100}).get("items", [])
        return [{"number": i["number"], "title": i["title"], "author": i["user"]["login"], "draft": bool(i.get("draft"))} for i in items]

    def workflow_runs(self, head_sha=None, branch=None):
        """[{"created_at", "actor", "event", "head_sha"}], oldest first."""
        params = {k: v for k, v in (("head_sha", head_sha), ("branch", branch)) if v}
        runs = self.pages(f"/repos/{self.repository}/actions/runs", params, limit=2)
        return sorted(({"created_at": r["created_at"], "actor": (r.get("actor") or {}).get("login"), "event": r["event"], "head_sha": r["head_sha"]}
                       for r in runs), key=lambda r: r["created_at"])
