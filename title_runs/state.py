"""The service's state: per followed PR, the heads seen, their status and the bot comment."""

import datetime
import json
import os
from pathlib import Path

WAITING, PAUSED, READY, RUNNING, DONE, FAILED, SUPERSEDED = "waiting", "paused", "ready", "running", "done", "failed", "superseded"


def now():
    return datetime.datetime.now(datetime.timezone.utc)


def parse(text):
    return datetime.datetime.fromisoformat(text.replace("Z", "+00:00")) if text else None


def iso(moment):
    return moment.astimezone(datetime.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class State:
    def __init__(self, path):
        self.path = Path(path)
        self.data = json.loads(self.path.read_text()) if self.path.exists() else {"prs": {}}

    def pr(self, number):
        return self.data["prs"].setdefault(str(number), {"heads": [], "comment_id": None, "comment_posts": []})

    def prs(self):
        return {int(number): entry for number, entry in self.data["prs"].items()}

    def current(self, number):
        heads = self.pr(number)["heads"]
        return heads[-1] if heads else None

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.data, indent=2, sort_keys=True))
        os.replace(temporary, self.path)
