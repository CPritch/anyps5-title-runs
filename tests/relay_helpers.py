"""A results repository checkout, a fake AnyPS5 (FakeForge), a small git history for patch-ids, and fixture events."""

import json
import os
import subprocess
import tempfile
from pathlib import Path

import helpers  # noqa: F401  (puts the repository on sys.path)

from title_runs import export, formats
from title_runs.relay import forge as forges

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
    B: A plus a commit that changes the code (a push after approval); C: A's change edited and rebased."""

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
        git(self.dir, "checkout", "-q", "main")
        self.git_dir = self.dir / ".git"
        self.m1 = m1


def event(name, **values):
    """A fixture event with its {PLACEHOLDERS} filled, keeping the type of each value."""
    def fill(node):
        if isinstance(node, dict):
            return {k: fill(v) for k, v in node.items()}
        if isinstance(node, list):
            return [fill(v) for v in node]
        if isinstance(node, str) and node.startswith("{") and node.endswith("}") and node[1:-1] in values:
            return values[node[1:-1]]
        return node
    return fill(json.loads((FIXTURES / f"{name}.json").read_text()))


class Stand:
    """A results repository's two branches as two checkouts (data: main, with claims and results; state: config, queue
    and comments) and the fake forge, in a temporary directory."""

    def __init__(self, testers=None):
        self.root = Path(tempfile.mkdtemp())
        self.history = History(self.root)
        self.checkout, self.state_dir = self.root / "data", self.root / "state"
        export.export(self.checkout, self.state_dir, "CPritch/AnyPS5")
        config = json.loads((self.state_dir / "config.json").read_text())
        config.update(maintainers=["CPritch", "notreally"], testers=testers or {"CPritch": {"machines": ["laptop"]}, "other": {"machines": ["desktop"]}})
        (self.state_dir / "config.json").write_text(json.dumps(config, indent=2))
        for directory in (self.checkout, self.state_dir):
            git(directory, "init", "-q", "-b", "main")
            git(directory, "add", "-A")
            git(directory, "commit", "-qm", "results repository")
        self.state = self.root / "forge.json"
        self.state.write_text(json.dumps({
            "repository": "CPritch/AnyPS5",
            "pulls": {"8104": {"number": 8104, "title": "perf(agc): stage the written elements", "author": "Celegans12", "state": "open",
                               "head": self.history.A, "commits": [self.history.A]}},
            "associations": {"CPritch": "OWNER", "collab": "COLLABORATOR", "Celegans12": "CONTRIBUTOR", "notreally": "NONE"}}))
        self.outbox = self.root / "outbox"

    def forge(self):
        return forges.FakeForge(self.state, self.outbox)

    def set_head(self, sha):
        data = json.loads(self.state.read_text())
        pull = data["pulls"]["8104"]
        pull["head"] = sha
        if sha not in pull["commits"]:
            pull["commits"].append(sha)
        self.state.write_text(json.dumps(data))

    def set_association(self, login, association):
        data = json.loads(self.state.read_text())
        data["associations"][login] = association
        self.state.write_text(json.dumps(data))

    def queue_event(self, name, payload, refresh=False, at=None):
        from title_runs.relay import queue
        workflow = queue.QueueWorkflow(self.state_dir, self.checkout, self.forge(), self.history.git_dir, None, "main", now=at, log=lambda *_: None)
        if refresh:
            workflow.refresh()
        else:
            workflow.handle(name, payload)
        changed = workflow.finish()
        git(self.state_dir, "add", "-A")
        if git(self.state_dir, "status", "--porcelain"):
            git(self.state_dir, "commit", "-qm", f"queue: {name}")
        return workflow, changed

    def queued(self):
        return json.loads((self.state_dir / "queue.json").read_text())

    def outbox_calls(self):
        return [json.loads(p.read_text()) for p in sorted(self.outbox.glob("*.json"))] if self.outbox.exists() else []

    def bodies(self):
        return [p.read_text() for p in sorted(self.outbox.glob("*.md"))] if self.outbox.exists() else []

    def push(self, files, actor="CPritch", at=None):
        """Commit files {path: data} as a tester's push and run the publish workflow on it."""
        from title_runs.relay import publish
        before = git(self.checkout, "rev-parse", "HEAD")
        for path, data in files.items():
            write(self.checkout, path, data if isinstance(data, str) else json.dumps(data, indent=1))
        git(self.checkout, "add", "-A")
        git(self.checkout, "commit", "-qm", f"push by {actor}")
        after = git(self.checkout, "rev-parse", "HEAD")
        report = publish.publish(self.state_dir, self.checkout, self.forge(), actor, before, after, at=at, log=lambda *_: None)
        git(self.state_dir, "add", "-A")
        if git(self.state_dir, "status", "--porcelain"):
            git(self.state_dir, "commit", "-qm", "publish")
        return report


NVIDIA = formats.machine_class("NVIDIA GeForce RTX 5060 Laptop GPU", "Linux 7.2.8")


def claim(head, machine="laptop", tester="CPritch", claimed="2026-10-21T12:00:00Z", hours=3):
    job = formats.job_id(8104, head)
    return formats.claim_path(job, machine), formats.make_claim(job, machine, tester, NVIDIA, ["PPSA04263"], formats.parse_time(claimed), hours, head=head)


def result(head, machine="laptop", tester="CPritch", trust="queue", outcome_b="rendering", verdict="no difference beyond the spread", diff=-0.33):
    job = formats.job_id(8104, head)
    data = {"format": 1, "job": job, "pr": 8104, "head": head, "base": "d97361bd0df0" + "0" * 28, "merge": "1" * 40, "machine": machine,
            "tester": tester, "class": NVIDIA, "machine_line": "NVIDIA GeForce RTX 5060 Laptop GPU, NVIDIA 615.71.09, Linux 7.2.8",
            "trust": trust, "status": "done", "sandbox": "bwrap", "started": "2026-10-21T12:05:00Z", "finished": "2026-10-21T12:55:00Z",
            "titles": {"PPSA04263": {"name": "Grand Theft Auto V", "version": "01.010.002", "scene": "Story Mode, the bank",
                                     "outcome": {"A": "rendering", "B": outcome_b},
                                     "verdict": {"verdict": verdict, "diff": diff, "diff_pct": diff / 78 * 100, "spread": 0.39, "gpu_diff": 0.07},
                                     "sides": {"A": {"p50": [78.2, 77.9], "p90": [87.6, 89.1], "p99": [108.9, 114.4], "gpu": [63.0, 62.6]},
                                               "B": {"p50": [78.0 + diff, 77.6 + diff], "p90": [87.9, 88.0], "p99": [109.5, 105.9], "gpu": [63.0, 62.7]}},
                                     "summary_lines": {"A": ['{"commit":"d97361bd0df0"}'], "B": ['{"commit":"' + head[:12] + '"}']}}}}
    return formats.result_path(job, machine), data
