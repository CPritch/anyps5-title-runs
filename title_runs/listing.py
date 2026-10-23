"""The pull requests of a repository, kept on disk for the All pull requests page: every open one, read from GitHub's
REST API without a sign-in, 100 to a request, only when the tester presses Refresh (each request is one of the 60 an
hour GitHub allows without a sign-in: 14 for AnyPS5's 1,314 open pull requests on 2026-10-23)."""

import datetime
import json
import os
from pathlib import Path

MAX_PAGES = 30  # 3,000 open pull requests


def shape(item):
    """A pull request as the page shows it, from the REST API's list of pull requests."""
    return {"number": item["number"], "title": item["title"], "author": (item.get("user") or {}).get("login", ""),
            "head": (item.get("head") or {}).get("sha", ""), "draft": bool(item.get("draft")),
            "labels": [label["name"] for label in item.get("labels") or []], "body": (item.get("body") or "")[:4000],
            "updated": item.get("updated_at", "")}


class Listing:
    def __init__(self, path, repository=None):
        self.path = Path(path)
        data = json.loads(self.path.read_text()) if self.path.exists() else {}
        # Until 2026-10-23 the listing was GraphQL's, with a sign-in: such a file is read again from the start.
        self.data = data if data.get("source") == "rest" else {"source": "rest", "prs": {}}
        if repository:
            self.data.setdefault("repository", repository)

    @classmethod
    def of(cls, state_dir, repository):
        """The listing of one repository (OWNER/NAME) in the state directory's cache."""
        return cls(Path(state_dir) / "cache" / f"pull-requests-{repository.replace('/', '-')}.json", repository)

    def refreshed(self):
        """When the listing was last read (ISO), or None."""
        return self.data.get("refreshed")

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.data))
        os.replace(temporary, self.path)

    def refresh(self, repo, max_pages=MAX_PAGES):
        """Every open pull request of repo (a gh.GitHubRepo), in place of what was listed. Returns how many."""
        items = repo.pages(f"/repos/{repo.repository}/pulls", {"state": "open", "sort": "updated", "direction": "desc"}, limit=max_pages)
        self.data["prs"] = {str(item["number"]): shape(item) for item in items}
        self.data["repository"] = repo.repository
        self.data["refreshed"] = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        self.save()
        return len(items)

    def get(self, number):
        return self.data["prs"].get(str(number))

    def open(self):
        return list(self.data["prs"].values())
