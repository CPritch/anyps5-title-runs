"""A small git history for the tests of source trees (sources.py) and local tests."""

import os
import subprocess
from pathlib import Path

import helpers  # noqa: F401  (puts the repository on sys.path)

GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com",
           "GIT_AUTHOR_DATE": "2026-10-21T10:00:00Z", "GIT_COMMITTER_DATE": "2026-10-21T10:00:00Z"}


def git(directory, *args):
    return subprocess.run(["git", "-C", str(directory), *args], capture_output=True, text=True, check=True,
                          env={**os.environ, **GIT_ENV}).stdout.strip()


def write(directory, name, text):
    (Path(directory) / name).parent.mkdir(parents=True, exist_ok=True)
    (Path(directory) / name).write_text(text)


class History:
    """main m1 -> m2; a PR's head A (one commit on m1); R: the same change rebased onto m2; B: A plus a commit that
    changes the code; C: A's change edited and rebased; D: a commit on m1 that conflicts with m2."""

    def __init__(self, root):
        self.dir = Path(root) / "anyps5"
        self.dir.mkdir()
        git(self.dir, "init", "-q", "-b", "main")
        write(self.dir, "core/a.cpp", "int a() { return 1; }\n")
        git(self.dir, "add", ".")
        git(self.dir, "commit", "-qm", "m1")
        m1 = git(self.dir, "rev-parse", "HEAD")
        git(self.dir, "checkout", "-qb", "pr")
        write(self.dir, "core/b.cpp", "int b() { return 2; }\n")
        git(self.dir, "add", ".")
        git(self.dir, "commit", "-qm", "perf: b")
        self.A = git(self.dir, "rev-parse", "HEAD")
        write(self.dir, "core/b.cpp", "int b() { return 3; }\n")
        git(self.dir, "commit", "-qam", "perf: b, changed after approval")
        self.B = git(self.dir, "rev-parse", "HEAD")
        git(self.dir, "checkout", "-q", "main")
        write(self.dir, "core/c.cpp", "int c() { return 4; }\n")
        git(self.dir, "add", ".")
        git(self.dir, "commit", "-qm", "m2")
        git(self.dir, "checkout", "-qb", "rebased")
        git(self.dir, "cherry-pick", self.A)
        self.R = git(self.dir, "rev-parse", "HEAD")
        git(self.dir, "checkout", "-qb", "edited", "main")
        write(self.dir, "core/b.cpp", "int b() { return 5; }\n")
        git(self.dir, "add", ".")
        git(self.dir, "commit", "-qm", "perf: b")
        self.C = git(self.dir, "rev-parse", "HEAD")
        git(self.dir, "checkout", "-qb", "conflicting", m1)
        write(self.dir, "core/c.cpp", "int c() { return 9; }\n")
        git(self.dir, "add", ".")
        git(self.dir, "commit", "-qm", "perf: c")
        self.D = git(self.dir, "rev-parse", "HEAD")
        git(self.dir, "checkout", "-q", "main")
        self.m2 = git(self.dir, "rev-parse", "main")
        self.git_dir = self.dir / ".git"
        self.m1 = m1
