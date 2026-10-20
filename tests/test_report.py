import copy
import tempfile
import unittest
from pathlib import Path

from helpers import make_config

from title_runs import poster, protocol, report
from title_runs.state import State


def summary(p50, gpu, commit):
    return {"commit": commit, "os": "Linux 7.2.8", "gpu": "NVIDIA GeForce RTX 5060 Laptop GPU", "driver": "615.71.09",
            "frame_ms": {"p50": p50, "p90": p50 + 9, "p99": p50 + 25, "max": p50 + 40}, "gpu_busy_ms_per_present": gpu,
            "presents": 700, "window": {"spec": "frames 3600:700", "first_present": 3600, "ms": 52000}}


def results(head, a=(73.4, 73.4), b=(65.2, 65.0), outcome_b="rendering", counts=True):
    runs = []
    for i, (pa, pb) in enumerate(zip(a, b), 1):
        runs.append({"run": f"r-A{i}", "side": "A", "counts": True, "capture": "counts", "summary": summary(pa, 61.4, "base")})
        runs.append({"run": f"r-B{i}", "side": "B", "counts": counts, "capture": "counts" if counts else "not counted: 3 pipeline builds",
                     "summary": summary(pb, 53.6, "merge") if counts else None})
    ab = {"window": {"spec": "3600:700", "dump_limit": 114, "from": "w"}, "runs": runs, "warm": {}}
    return {"pr": 10, "head": head, "merge": "m" * 40, "base": "b" * 40, "started": "2026-10-21T02:00:00+01:00", "status": "done",
            "sandbox": "bwrap", "machine": "box",
            "titles": {"PPSA04263": {"name": "Grand Theft Auto V", "version": "01.010.002", "scene": "Story Mode, loaded",
                                     "outcome": {"A": "rendering", "B": outcome_b}, "ab": ab, "verdict": protocol.verdict(runs)}}}


class Verdict(unittest.TestCase):
    def test_a_difference_beyond_both_spreads(self):
        v = results("h1")["titles"]["PPSA04263"]["verdict"]
        self.assertEqual(v["verdict"], "faster")
        self.assertAlmostEqual(v["diff"], -8.3)
        self.assertAlmostEqual(v["spread"], 0.2)

    def test_within_the_spread(self):
        v = results("h1", a=(73.4, 73.9), b=(73.5, 73.6))["titles"]["PPSA04263"]["verdict"]
        self.assertEqual(v["verdict"], "no difference beyond the spread")

    def test_not_enough_counted_runs(self):
        v = results("h1", counts=False)["titles"]["PPSA04263"]["verdict"]
        self.assertEqual(v["verdict"], "not enough counted runs")


class Render(unittest.TestCase):
    def setUp(self):
        self.config = make_config()

    def test_the_comment_holds_what_a_developer_needs(self):
        body = report.render(self.config, 10, results("h" * 40), [], ["A note."])
        self.assertTrue(body.startswith("<!-- anyps5-title-runs machine=box -->"))
        for text in ("`refs/pull/10/merge`", "Head `hhhhhhhhh`", "main `bbbbbbbbb`", "NVIDIA GeForce RTX 5060 Laptop GPU, driver 615.71.09, Linux 7.2.8",
                     "bubblewrap", "| Grand Theft Auto V (PPSA04263 01.010.002) | Story Mode, loaded | rendering | rendering |",
                     "Graphics Mode Performance", "| p50 frame | 73.4, 73.4 ms | 65.2, 65.0 ms |", "**faster**: -8.30 ms p50",
                     "<details><summary>Summary lines", "Screenshot:", "A note.", "never game files"):
            self.assertIn(text, body)
        self.assertNotIn("Earlier heads", body)

    def test_no_sandbox_is_said(self):
        data = results("h1")
        data["sandbox"] = "none"
        self.assertIn("**none** (the tester turned the sandbox off)", report.render(self.config, 10, data, []))

    def test_history_lists_earlier_heads_newest_first(self):
        old1 = report.head_summary(results("a" * 40, b=(73.0, 73.1)))
        old2 = report.head_summary(results("c" * 40))
        body = report.render(self.config, 10, results("d" * 40), [old1, old2])
        self.assertIn("<details><summary>Earlier heads</summary>", body)
        self.assertLess(body.index("`ccccccccc`"), body.index("`aaaaaaaaa`"))
        self.assertIn("73.4 -> 73.0 ms (-0.35)", body)

    def test_runs_that_did_not_count_are_listed(self):
        body = report.render(self.config, 10, results("h1", counts=False), [])
        self.assertIn("Runs that did not count: r-B1: not counted: 3 pipeline builds", body)


class EditOrNew(unittest.TestCase):
    def test_first_results_are_a_new_comment(self):
        self.assertEqual(report.decide(None, report.head_summary(results("h1")), False)[0], "new")

    def test_same_outcome_and_verdict_edits(self):
        before, now = report.head_summary(results("h1")), report.head_summary(results("h2", b=(65.4, 65.3)))
        self.assertEqual(report.decide(before, now, True), ("edit", "outcomes and verdicts are unchanged"))

    def test_an_outcome_change_is_a_new_comment(self):
        before, now = report.head_summary(results("h1")), report.head_summary(results("h2", outcome_b="crashed (title did not advance)"))
        action, reason = report.decide(before, now, True)
        self.assertEqual(action, "new")
        self.assertIn("this PR went from rendering to crashed", reason)

    def test_a_verdict_change_is_a_new_comment(self):
        before = report.head_summary(results("h1", a=(73.4, 73.9), b=(73.5, 73.6)))
        now = report.head_summary(results("h2", a=(73.4, 73.4), b=(75.0, 75.1)))
        self.assertEqual(report.decide(before, now, True), ("new", "PPSA04263: the frame-time verdict went from no difference beyond the spread to slower"))

    def test_back_to_no_difference_edits(self):
        before = report.head_summary(results("h1"))
        now = report.head_summary(results("h2", a=(73.4, 73.9), b=(73.5, 73.6)))
        self.assertEqual(report.decide(before, now, True)[0], "edit")


class DryRunPoster(unittest.TestCase):
    def test_the_outbox_gets_the_body_and_the_call(self):
        config = make_config()
        state = State(Path(tempfile.mkdtemp()) / "state.json")
        state.pr(10)["heads"].append({"head": "h1", "status": "done", "seen": "2026-10-20T00:00:00Z"})
        first = poster.post(config, state, 10, "body 1", "new", "first")
        self.assertEqual((first["method"], first["path"]), ("POST", "/repos/o/r/issues/10/comments"))
        self.assertTrue(Path(first["body_file"]).read_text() == "body 1")
        second = poster.post(config, state, 10, "body 2", "edit", "same")
        self.assertEqual((second["method"], second["path"]), ("PATCH", "/repos/o/r/issues/comments/dry-run-10"))
        self.assertTrue(all(record["dry_run"] for record in state.pr(10)["comment_posts"]))

    def test_the_real_poster_is_not_used_unless_enabled(self):
        config = make_config()
        state = State(Path(tempfile.mkdtemp()) / "state.json")
        record = poster.post(config, state, 10, "body", "new", "first", dry_run=False)
        self.assertTrue(record["dry_run"])


if __name__ == "__main__":
    unittest.main()
