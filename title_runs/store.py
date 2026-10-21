"""The results repository as the client sees it, through git: a local bare repository (the stand-in) or GitHub over
https with the tester's token. This and relay/forge.py are the only places that talk to GitHub.

Two checkouts under the client's state directory: main (claims and results; the client pushes here) and state (the
queue and the configuration; read only). The token is handed to git through a credential helper that reads it from the
environment variable, so it is never written into a URL or a git config file.
"""

import json
import os
import subprocess
import time
from pathlib import Path

from . import formats


CHECK_JOB = "0-000000000000"


class StoreError(RuntimeError):
    pass


class ResultsRepo:
    def __init__(self, url, workdir, token_env=None, state_branch="state", author=("anyps5-title-runs", "title-runs@localhost")):
        self.url, self.dir, self.token_env, self.state_branch, self.author = url, Path(workdir), token_env, state_branch, author
        self.main, self.state = self.dir / "main", self.dir / "state"

    def run(self, directory, *args):
        prefix = ["git"]
        if self.token_env and os.environ.get(self.token_env):
            prefix += ["-c", "credential.helper=", "-c",
                       f"credential.helper=!f() {{ echo username=x-access-token; echo \"password=${self.token_env}\"; }}; f"]
        env = {**os.environ, "GIT_AUTHOR_NAME": self.author[0], "GIT_AUTHOR_EMAIL": self.author[1], "GIT_COMMITTER_NAME": self.author[0],
               "GIT_COMMITTER_EMAIL": self.author[1], "GIT_TERMINAL_PROMPT": "0"}
        return subprocess.run([*prefix, "-C", str(directory), *args], capture_output=True, text=True, env=env)

    def git(self, directory, *args, check=True):
        result = self.run(directory, *args)
        if check and result.returncode != 0:
            raise StoreError(f"git {' '.join(args[:3])}: {result.stderr.strip()[:300]}")
        return result.stdout.strip()

    def sync(self):
        """Clone or update both checkouts to the remote's tips (local changes in them are discarded)."""
        self.dir.mkdir(parents=True, exist_ok=True)
        for path, branch in ((self.main, "main"), (self.state, self.state_branch)):
            if not (path / ".git").exists():
                self.git(self.dir, "clone", "-q", "--branch", branch, "--single-branch", self.url, str(path))
            else:
                self.git(path, "fetch", "-q", "origin", branch)
                self.git(path, "reset", "-q", "--hard", f"origin/{branch}")
                self.git(path, "clean", "-q", "-fd")

    def can_read_and_write(self, machine):
        """The setup's connection check: read the queue, then push a claim for job 0 (which no PR has) and remove it."""
        self.sync()
        queue = self.queue()
        path = f"claims/{CHECK_JOB}/{machine}.json"
        self.write({path: {"check": formats.iso(formats.now())}}, f"check: {machine} can write")
        self.write({path: None}, f"check: {machine} removed its check file")
        return len(queue["entries"])

    def config(self):
        return formats.check_config(json.loads((self.state / "config.json").read_text()))

    def queue(self):
        return formats.check_queue(json.loads((self.state / "queue.json").read_text()))

    def comments(self):
        path = self.state / "comments.json"
        return json.loads(path.read_text()) if path.exists() else formats.empty_comments()

    def _read(self, kind, check):
        out = {}
        for path in sorted((self.main / kind).glob("*/*.json")):
            relative = f"{kind}/{path.parent.name}/{path.name}"
            try:
                data = check(json.loads(path.read_text()), relative)
            except (formats.FormatError, json.JSONDecodeError):
                continue
            out.setdefault(data["job"], {})[data["machine"]] = data
        return out

    def claims(self):
        return self._read("claims", formats.check_claim)

    def results(self):
        return self._read("results", formats.check_result)

    def write(self, files, message, attempts=4):
        """Write {path: data or None (remove)} to main, commit and push; on a rejected push, rebase and retry."""
        for path, data in files.items():
            target = self.main / path
            if data is None:
                target.unlink(missing_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(json.dumps(data, indent=1) + "\n")
        self.git(self.main, "add", "-A", *files)
        if not self.git(self.main, "status", "--porcelain"):
            return None
        self.git(self.main, "commit", "-q", "-m", message)
        for attempt in range(attempts):
            if self.run(self.main, "push", "-q", "origin", "HEAD:main").returncode == 0:
                return self.git(self.main, "rev-parse", "HEAD")
            self.git(self.main, "pull", "-q", "--rebase", "origin", "main")
            time.sleep(1 + attempt)
        raise StoreError(f"could not push {message!r}")
