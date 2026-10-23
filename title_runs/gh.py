"""GitHub's REST API, read only, with the tester's sign-in: a project's open pull requests, a pull request's head and
state, the workflow runs that tell who pushed a head (local_tests.py), and who signed in (auth.py). Nothing here
writes to GitHub."""

import json
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.github.com"


class GitHubError(RuntimeError):
    pass


class GitHubRepo:
    """One repository, read with a token (or without one: GitHub then allows 60 requests an hour)."""

    def __init__(self, repository, token=None):
        self.repository = repository
        self.token = token
        self._login = None

    def call(self, path, params=None):
        url = f"{API}{path}" + (f"?{urllib.parse.urlencode(params)}" if params else "")
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60) as response:
                return json.loads(response.read() or b"null")
        except urllib.error.HTTPError as error:
            raise GitHubError(f"GET {path}: HTTP {error.code} {error.read()[:300]!r}") from error

    def pages(self, path, params=None, limit=10):
        out = []
        for page in range(1, limit + 1):
            batch = self.call(path, params={**(params or {}), "per_page": 100, "page": page})
            items = batch.get("workflow_runs", []) if isinstance(batch, dict) else batch
            out += items
            if len(items) < 100:
                break
        return out

    def login(self):
        """The signed-in account."""
        if self._login is None and self.token:
            self._login = self.call("/user")["login"]
        return self._login

    def pull(self, number):
        """{"number", "title", "author", "head", "head_ref", "state" (open, closed or merged), "labels"}."""
        data = self.call(f"/repos/{self.repository}/pulls/{number}")
        return {"number": number, "title": data["title"], "author": data["user"]["login"], "head": data["head"]["sha"],
                "head_ref": data["head"]["ref"], "state": "merged" if data.get("merged_at") else data["state"],
                "labels": [label["name"] for label in data.get("labels", [])]}

    def workflow_runs(self, head_sha=None, branch=None):
        """[{"created_at", "actor", "event", "head_sha"}], oldest first."""
        params = {k: v for k, v in (("head_sha", head_sha), ("branch", branch)) if v}
        runs = self.pages(f"/repos/{self.repository}/actions/runs", params, limit=2)
        return sorted(({"created_at": r["created_at"], "actor": (r.get("actor") or {}).get("login"), "event": r["event"], "head_sha": r["head_sha"]}
                       for r in runs), key=lambda r: r["created_at"])
