"""The relay's world for tests: a fake GitHub, a small git history for patch-ids, a results checkout, claims and results."""

import json
import os
import subprocess
import tempfile
from pathlib import Path

import helpers  # noqa: F401  (puts the repository on sys.path)

from title_runs import formats, gh

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "events"
GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com",
           "GIT_AUTHOR_DATE": "2026-10-21T10:00:00Z", "GIT_COMMITTER_DATE": "2026-10-21T10:00:00Z"}


def git(directory, *args):
    return subprocess.run(["git", "-C", str(directory), *args], capture_output=True, text=True, check=True,
                          env={**os.environ, **GIT_ENV}).stdout.strip()


def write(directory, name, text):
    (Path(directory) / name).parent.mkdir(parents=True, exist_ok=True)
    (Path(directory) / name).write_text(text)


class History:
    """main m1 -> m2; the PR's approved head A (one commit on m1); R: the same change rebased onto m2 (same patch-id);
    B: A plus a commit that changes the code (a push after approval); C: A's change edited and rebased; D: a commit on
    m1 that conflicts with m2."""

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


class Stand:
    """The relay's world: a fake GitHub (AnyPS5 and the results repository) with a clock the tests set, the History as
    AnyPS5's git objects, and a state directory standing in for the results repository's checkout."""

    ANYPS5, RESULTS = "CPritch/AnyPS5", "CPritch/anyps5-title-runs-results"

    def __init__(self, maintainers=("CPritch",)):
        self.root = Path(tempfile.mkdtemp())
        self.history = History(self.root)
        self.time = "2026-10-21T12:00:00Z"
        self.github = gh.FakeGitHub.create(self.root / "github.json", self.root / "outbox")
        self.github.clock = lambda: self.time
        anyps5 = self.github.repo(self.ANYPS5)
        anyps5["pulls"]["8104"] = {"number": 8104, "title": "perf(agc): stage the written elements", "author": "Celegans12", "state": "open",
                                   "head": self.history.A, "head_ref": "perf/staging", "commits": [self.history.A], "labels": []}
        anyps5["runs"].append({"head_sha": self.history.A, "created_at": "2026-10-21T11:00:00Z", "actor": "Celegans12", "event": "pull_request",
                               "branch": "perf/staging"})
        anyps5["permissions"].update({"CPritch": "admin", "collab": "write", "Celegans12": "read"})
        self.github.repo(self.RESULTS)["permissions"].update({"CPritch": "admin"})
        self.github.save()
        self.state = self.root / "state"
        self.state.mkdir()
        (self.state / "config.json").write_text(json.dumps({"format": 1, "repository": self.ANYPS5, "results_repository": self.RESULTS,
                                                            "maintainers": list(maintainers), "label": "title-test"}))

    def at(self, stamp):
        self.time = stamp
        return self

    def app(self):
        return self.github.as_(self.ANYPS5, identity="title-runs[bot]")

    def workflow(self):
        return self.github.as_(self.RESULTS, identity="github-actions[bot]")

    def user(self, login, repository=None):
        return self.github.as_(repository or self.RESULTS, login)

    def poll(self, refresh=True):
        from title_runs.relay import relay
        self.relay = relay.Relay(self.state, self.app(), self.workflow(), self.history.git_dir, None, "main",
                                 now=formats.parse_time(self.time), log=lambda *_: None)
        return self.relay.run(refresh)

    # -- AnyPS5 -------------------------------------------------------------------------------------------------------

    def label(self, actor="CPritch", name="title-test"):
        self.user(actor, self.ANYPS5).add_labels(8104, [name])

    def unlabel(self, actor="CPritch", name="title-test"):
        self.user(actor, self.ANYPS5).remove_label(8104, name)

    def push(self, sha, actor="Celegans12", run=True):
        self.github.reload()
        pull = self.github.repo(self.ANYPS5)["pulls"]["8104"]
        pull["head"] = sha
        pull["commits"].append(sha)
        if run:
            self.github.repo(self.ANYPS5)["runs"].append({"head_sha": sha, "created_at": self.time, "actor": actor, "event": "pull_request",
                                                          "branch": "perf/staging"})
        self.github.save()

    def command(self, body, actor="CPritch"):
        return self.user(actor, self.ANYPS5).create_comment(8104, body)

    # -- the results repository ---------------------------------------------------------------------------------------

    def register(self, tester="CPritch", machine="laptop", info=None, opened_by=None):
        data = {"format": 1, "tester": tester, "machine": machine, "class": info or NVIDIA, "titles": ["PPSA04263"]}
        body = formats.payload_body("register", data, f"Register {machine}.")
        return self.user(opened_by or tester).create_issue(f"Machine: {tester}/{machine}", body)

    def approve_machine(self, issue, actor="CPritch", label="approved"):
        self.user(actor).add_labels(issue, [label])

    def queued(self):
        return json.loads((self.state / "queue.json").read_text())

    def registry(self):
        return json.loads((self.state / "registry.json").read_text())

    def calls(self, who=None, action=None):
        out = [json.loads(p.read_text()) for p in sorted((self.root / "outbox").glob("*.json"))]
        return [c for c in out if (who is None or c["as"] == who) and (action is None or c["action"] == action)]

    def bodies(self, who="title-runs[bot]"):
        tag = "-" + who.replace("[", "").replace("]", "") + "-"
        return [p.read_text() for p in sorted((self.root / "outbox").glob("*.md")) if tag in p.name]

    def issue(self, number):
        self.github.reload()
        return self.github.repo(self.RESULTS)["issues"][str(number)]

    def issue_comments(self, number):
        return self.workflow().comments(issue=number)

    def pull_labels(self):
        return self.app().pull(8104)["labels"]


NVIDIA = formats.machine_class("NVIDIA GeForce RTX 5060 Laptop GPU", "Linux 7.2.8", "NVIDIA 615.71.09")
NVIDIA_TOO = formats.machine_class("NVIDIA GeForce RTX 5060 Laptop GPU", "Linux 6.17.1", "NVIDIA 615.42.01")


def claim(head, machine="laptop", tester="CPritch", claimed="2026-10-21T12:00:00Z", hours=3, info=None):
    job = formats.job_id(8104, head)
    return formats.make_claim(job, machine, tester, info or NVIDIA, ["PPSA04263"], formats.parse_time(claimed), hours, head=head)


def result(head, machine="laptop", tester="CPritch", trust="queue", outcome_b="rendering", a=(78.0, 78.0), b=(77.6, 77.7), info=None):
    job = formats.job_id(8104, head)
    return {"format": 1, "job": job, "pr": 8104, "head": head, "base": "d97361bd0df0" + "0" * 28, "merge": "1" * 40, "machine": machine,
            "tester": tester, "class": info or NVIDIA, "machine_line": "NVIDIA GeForce RTX 5060 Laptop GPU, NVIDIA 615.71.09, Linux 7.2.8",
            "trust": trust, "status": "done", "sandbox": "bwrap", "started": "2026-10-21T12:05:00Z", "finished": "2026-10-21T12:55:00Z",
            "titles": {"PPSA04263": {"name": "Grand Theft Auto V", "version": "01.010.002", "scene": "Story Mode, the bank",
                                     "outcome": {"A": "rendering", "B": outcome_b},
                                     "verdict": {"verdict": "no difference"},
                                     "sides": {"A": {"p50": list(a), "p90": [87.6, 89.1], "p99": [108.9, 114.4], "gpu": [63.0, 62.6]},
                                               "B": {"p50": list(b), "p90": [87.9, 88.0], "p99": [109.5, 105.9], "gpu": [63.0, 62.7]}},
                                     "summary_lines": {"A": ['{"commit":"d97361bd0df0"}'], "B": ['{"commit":"' + head[:12] + '"}']}}}}
