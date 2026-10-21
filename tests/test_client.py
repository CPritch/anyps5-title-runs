"""The client against the stand-in (a bare results repository with its publish hook, the fake AnyPS5), with job.run
replaced by a fake that records what it was asked to build and calls the client's last check before "building"."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from helpers import make_config
from relay_helpers import History, git

from title_runs import client, formats, sources, standin

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


class Setup(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.history = History(self.root)
        self.stand = standin.create(self.root / "standin", "CPritch/AnyPS5", ["CPritch"], {"CPritch": {"machines": ["box"]}},
                                    self.history.dir, self.history.m2,
                                    [{"number": 8104, "title": "perf(agc): stage", "author": "Celegans12", "head": self.history.A}],
                                    {"CPritch": "OWNER", "Celegans12": "CONTRIBUTOR"})
        for name in ("B", "R"):
            git(self.stand.anyps5, "update-ref", f"refs/heads/keep-{name}", getattr(self.history, name))
        self.config = make_config(results_url=str(self.stand.results), tester="CPritch", machine="box",
                                  repo_dir=self.history.dir, remote=str(self.stand.anyps5))
        self.client = client.Client(self.config, log=lambda *_: None, info=INFO)
        self.built = []

    def fake_run(self, before_build=None):
        def run(config, state_dir, pr, head, log, recheck=None, progress=None, should_stop=None):
            if before_build:
                before_build()
            stop = recheck() if recheck else None
            if stop:
                return {"pr": pr, "head": head, "started": "2026-10-21T12:00:00+00:00", "status": "superseded", "detail": stop, "titles": {}}
            self.built.append(head)
            return fake_results(pr, head)
        return mock.patch("title_runs.job.run", side_effect=run)

    def comments(self):
        return [json.loads(p.read_text()) for p in sorted((self.stand.root / "outbox").glob("*.json"))]


class PushAfterLabel(Setup):
    def test_the_push_after_the_label_is_not_built(self):
        h = self.history
        self.stand.label(8104, "CPritch")
        self.stand.push(8104, h.B, "Celegans12")
        with self.fake_run(), mock.patch.object(client.Client, "allowed_now", return_value=(True, "")):
            self.assertEqual(self.client.run_next(), f"ran {formats.job_id(8104, h.A)}")
        self.assertEqual(self.built, [h.A])
        self.client.repo.sync()
        self.assertEqual(list(self.client.repo.results()), [formats.job_id(8104, h.A)])
        self.assertEqual([c["action"] for c in self.comments()], ["new", "edit", "edit"])
        body = sorted((self.stand.root / "outbox").glob("*.md"))[-1].read_text()
        self.assertIn(f"`{h.B[:9]}` pushed after approval by @Celegans12: **not checked**", body)
        self.assertIn("| box |", body)

    def test_approval_moving_on_just_before_the_build_stops_the_job(self):
        h = self.history
        self.stand.label(8104, "CPritch")
        self.stand.push(8104, h.B, "Celegans12")
        approve = lambda: self.stand.command(8104, f"/title-test sha={h.B[:10]}", "CPritch", "OWNER")  # noqa: E731
        with self.fake_run(before_build=approve):
            self.assertIsNone(self.client.run(8104, h.A))
        self.assertEqual(self.built, [])
        self.client.repo.sync()
        self.assertEqual(self.client.repo.claims(), {})
        self.assertEqual(self.client.repo.results(), {})

    def test_a_head_the_queue_does_not_name_is_not_claimed(self):
        h = self.history
        self.stand.label(8104, "CPritch")
        with self.fake_run(), self.assertRaises(RuntimeError):
            self.client.run(8104, h.B)
        self.client.repo.sync()
        self.assertEqual(self.client.repo.claims(), {})


class TesterTrust(Setup):
    def test_unchecked_head_needs_the_tester_trust_and_is_marked(self):
        h = self.history
        with self.fake_run(), self.assertRaises(RuntimeError):
            self.client.run(8104, h.A, "tester", author="Celegans12")
        self.client.trust.grant("head", "Celegans12", 8104, h.A)
        self.client.status.update(job={"author": "Celegans12"})
        with self.fake_run():
            data = self.client.run(8104, h.A, "tester", author="Celegans12")
        self.assertEqual(data["trust"], "tester")
        body = sorted((self.stand.root / "outbox").glob("*.md"))[-1].read_text()
        self.assertIn("**Run on the tester's trust**", body)


class Sources(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.history = History(self.root)
        self.clone = self.root / "clone"
        git(self.root, "clone", "-q", str(self.history.dir), str(self.clone))

    def test_approved_head_merged_onto_main_the_same_on_every_machine(self):
        h = self.history
        main = sources.fetch_approved(self.clone, "origin", h.A)
        self.assertEqual(main, h.m2)
        merges = []
        for name in ("one", "two"):
            tree = sources.worktree(self.clone, self.root / name, main)
            merges.append(sources.merge_onto(tree, main, h.A))
        self.assertEqual(merges[0], merges[1])
        self.assertEqual(git(self.root / "one", "rev-parse", "HEAD^2"), h.A)

    def test_a_conflict_is_reported(self):
        h = self.history
        main = sources.fetch_approved(self.clone, "origin", h.D)
        tree = sources.worktree(self.clone, self.root / "c", main)
        with self.assertRaises(sources.SourceError) as raised:
            sources.merge_onto(tree, main, h.D)
        self.assertIn("conflicts in core/c.cpp", str(raised.exception))


class Trust(unittest.TestCase):
    def test_scopes_and_revoke(self):
        from title_runs import trust
        store = trust.TrustStore(Path(tempfile.mkdtemp()) / "trust.json")
        at = formats.parse_time("2026-10-21T12:00:00Z")
        store.grant("head", "alice", 1, "a" * 40, at)
        store.grant("pr", "bob", 2, "b" * 40, at)
        store.grant("author", "carol", 3, "c" * 40, at)
        self.assertTrue(store.allows(1, "alice", "a" * 40, at))
        self.assertIsNone(store.allows(1, "alice", "f" * 40, at))
        self.assertTrue(store.allows(2, "bob", "f" * 40, at))
        self.assertIsNone(store.allows(5, "bob", "f" * 40, at))
        self.assertTrue(store.allows(9, "carol", "f" * 40, formats.parse_time("2026-11-19T12:00:00Z")))
        self.assertIsNone(store.allows(9, "carol", "f" * 40, formats.parse_time("2026-11-21T12:00:00Z")))
        store.revoke(0)
        self.assertIsNone(trust.TrustStore(store.path).allows(1, "alice", "a" * 40, at))


if __name__ == "__main__":
    unittest.main()
