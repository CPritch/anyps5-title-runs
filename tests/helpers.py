import atexit
import datetime
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Every test's temporary folders (git histories, state) go in one folder per run, removed when the run ends:
# left in /tmp they filled it (10,000 folders, 2.4 GB) and the suite failed with no space left.
_RUN_DIR = tempfile.mkdtemp(prefix="title-runs-tests-")
tempfile.tempdir = _RUN_DIR
atexit.register(shutil.rmtree, _RUN_DIR, True)

from title_runs import config as configs  # noqa: E402

UTC = datetime.timezone.utc


def at(text):
    return datetime.datetime.fromisoformat(text).replace(tzinfo=UTC)


def make_pr(number, head, updated="2026-10-20T10:00:00Z", author="alice", state="OPEN", body="", labels=(), committer=None,
            committed="2026-10-20T09:00:00Z", draft=False):
    return {"number": number, "title": f"PR {number}", "url": f"https://github.com/o/r/pull/{number}", "state": state, "isDraft": draft,
            "updatedAt": updated, "mergeable": "MERGEABLE", "baseRefName": "main", "headRefName": f"b{number}", "headRefOid": head,
            "author": {"login": author}, "labels": {"nodes": [{"name": n} for n in labels]}, "body": body,
            "commits": {"nodes": [{"commit": {"oid": head, "committedDate": committed, "author": {"user": {"login": committer or author}}}}]}}


INFO = {"gpu": "NVIDIA GeForce RTX 5060 Laptop GPU", "driver": "NVIDIA 615.71.09", "os": "Linux 7.2.8"}


def fake_results(pr, head, status="done"):
    return {"pr": pr, "head": head, "started": "2026-10-21T12:00:00+00:00", "finished": "2026-10-21T12:50:00+00:00", "status": status,
            "sandbox": "bwrap", "base": "d" * 40, "merge": "e" * 40,
            "titles": {"PPSA04263": {"name": "Grand Theft Auto V", "version": "01.010.002", "scene": "the bank",
                                     "outcome": {"A": "rendering", "B": "rendering"},
                                     "verdict": {"verdict": "no difference beyond the spread", "diff": -0.3, "diff_pct": -0.4, "spread": 0.4, "gpu_diff": 0.1,
                                                 "sides": {"A": {"p50": [78.2, 77.9], "p90": [87.6, 89.1], "p99": [108.9, 114.4], "gpu": [63.0, 62.6]},
                                                           "B": {"p50": [77.9, 77.5], "p90": [87.9, 88.0], "p99": [109.5, 105.9], "gpu": [63.0, 62.7]}}},
                                     "ab": {"runs": [{"run": f"r{i}", "side": s, "counts": True, "summary": {"gpu": INFO["gpu"], "driver": INFO["driver"],
                                                                                                         "os": INFO["os"], "frame_ms": {"p50": 78}}}
                                                     for i, s in enumerate("ABAB")]}}}}


CONFIG = """
state_dir = "{state}"
[tester]
name = "tester"
machine = "box"
[titles.PPSA04263]
dump = "/nonexistent/dump"
graphics_mode = "Performance"
"""


def make_config(**overrides):
    directory = Path(tempfile.mkdtemp())
    path = directory / "config.toml"
    path.write_text(CONFIG.format(state=directory / "state"))
    config = configs.load(path)
    for key, value in overrides.items():
        setattr(config, key, value)
    return config


class FakeClient:
    """A GraphQL client that serves listing pages in order and records the variables of each query."""

    def __init__(self, pages=(), direct=None):
        self.pages = list(pages)
        self.direct = direct or {}
        self.calls = []
        self.spent = 0
        self.remaining = 5000

    def query(self, query, variables=None):
        self.calls.append(variables)
        if "pullRequests(" in query:
            nodes, more = self.pages.pop(0)
            return {"repository": {"pullRequests": {"pageInfo": {"hasNextPage": more, "endCursor": f"c{len(self.calls)}"}, "nodes": nodes}}}
        return {"repository": {f"pr{n}": pr for n, pr in self.direct.items()}}
