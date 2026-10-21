"""The results repository as the client sees it: a read-only git checkout of the public repository (queue, registry,
claims and results the workflow accepted, its config). The client never pushes to it; it comments through the tester's
own sign-in (auth.py, client.py)."""

import json
import os
import subprocess
from pathlib import Path

from . import formats


class StoreError(RuntimeError):
    pass


class ResultsRepo:
    def __init__(self, url, workdir):
        self.url, self.dir = url, Path(workdir)

    def git(self, *args, cwd=None):
        result = subprocess.run(["git", "-C", str(cwd or self.dir), *args], capture_output=True, text=True, env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
        if result.returncode != 0:
            raise StoreError(f"git {' '.join(args[:3])}: {result.stderr.strip()[:300]}")
        return result.stdout.strip()

    def sync(self):
        if not (self.dir / ".git").exists():
            self.dir.parent.mkdir(parents=True, exist_ok=True)
            self.git("clone", "-q", "--depth", "50", self.url, str(self.dir), cwd=self.dir.parent)
        else:
            self.git("fetch", "-q", "--depth", "50", "origin", "main")
            self.git("reset", "-q", "--hard", "origin/main")

    def read(self, name, default):
        path = self.dir / name
        return json.loads(path.read_text()) if path.exists() else default

    def config(self):
        return formats.check_config(self.read("config.json", None))

    def queue(self):
        return formats.check_queue(self.read("queue.json", formats.empty_queue("")))

    def registry(self):
        return self.read("registry.json", formats.empty_registry())

    def claims(self):
        return self.read("claims.json", {})

    def cursors(self):
        return self.read("cursors.json", {})

    def jobs(self):
        return self.read("jobs.json", {})

    def comments(self):
        return self.read("comments.json", formats.empty_comments())

    def results(self):
        out = {}
        for path in sorted((self.dir / "results").glob("*/*.json")):
            data = json.loads(path.read_text())
            out.setdefault(data["job"], {})[data["machine"]] = data
        return out
