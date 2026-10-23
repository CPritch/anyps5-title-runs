"""protocol.verdict: p50, p90, p99 and GPU per side over the counted runs, and the per-machine rule (a difference
counts when it is larger than both sides' spreads and than 1 % of main's p50)."""

import unittest

import helpers  # noqa: F401

from title_runs import protocol


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
        self.assertEqual(v["verdict"], "no difference")

    def test_not_enough_counted_runs(self):
        v = results("h1", counts=False)["titles"]["PPSA04263"]["verdict"]
        self.assertEqual(v["verdict"], "not enough counted runs")


if __name__ == "__main__":
    unittest.main()
