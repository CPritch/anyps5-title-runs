"""The tester's own trust, from the trust dialog (DESIGN.md): run code no maintainer approved, in one of three scopes.

- "head": this PR's current head only (the SHA the dialog showed);
- "pr": this author, for this PR (any of its heads);
- "author": this author, for 30 days, any PR.

Kept in the client's state directory (trust.json), listed in Settings, each revocable. A result run this way is marked
"tester" and posted apart from the maintainers' queue.
"""

import datetime
import json
import os
from pathlib import Path

from . import formats

SCOPES = ("head", "pr", "author")
AUTHOR_DAYS = 30


class TrustStore:
    def __init__(self, path):
        self.path = Path(path)
        self.entries = json.loads(self.path.read_text())["entries"] if self.path.exists() else []

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps({"format": 1, "entries": self.entries}, indent=2))
        os.replace(temporary, self.path)

    def grant(self, scope, author, pr, head, at=None):
        if scope not in SCOPES:
            raise ValueError(f"scope {scope!r} is not one of {', '.join(SCOPES)}")
        at = at or formats.now()
        entry = {"scope": scope, "author": author, "granted": formats.iso(at)}
        if scope in ("head", "pr"):
            entry["pr"] = pr
        if scope == "head":
            entry["head"] = head
        if scope == "author":
            entry["until"] = formats.iso(at + datetime.timedelta(days=AUTHOR_DAYS))
        self.entries.append(entry)
        self.save()
        return entry

    def revoke(self, index):
        removed = self.entries.pop(index)
        self.save()
        return removed

    def live(self, at=None):
        at = at or formats.now()
        return [e for e in self.entries if "until" not in e or formats.parse_time(e["until"]) > at]

    def allows(self, pr, author, head, at=None):
        """The entry that lets this head run, or None."""
        for entry in self.live(at):
            if entry["author"] != author:
                continue
            if entry["scope"] == "author" or (entry["scope"] == "pr" and entry["pr"] == pr) or (entry["scope"] == "head" and entry.get("head") == head):
                return entry
        return None

    @staticmethod
    def describe(entry):
        if entry["scope"] == "head":
            return f"{entry['author']}: #{entry['pr']} at {entry['head'][:9]} only"
        if entry["scope"] == "pr":
            return f"{entry['author']}: #{entry['pr']}, any head"
        return f"{entry['author']}: any PR, until {entry['until'][:10]}"
