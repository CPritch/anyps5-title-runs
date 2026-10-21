"""Stop starts no more games: protocol.Protocol.ab checks should_stop before each warm-up and before repeating a run
that didn't count (a run Stop ended doesn't count)."""

import unittest
from unittest import mock

import helpers  # noqa: F401

from title_runs import protocol


def bare(stop_after=None):
    p = object.__new__(protocol.Protocol)
    p.sides = [mock.Mock(key="A"), mock.Mock(key="B")]
    p.progress = None
    calls = {"games": 0}

    def should_stop():
        return "stopped by the tester" if stop_after is not None and calls["games"] >= stop_after else None
    p.should_stop = should_stop
    return p, calls


class StopStartsNothing(unittest.TestCase):
    def test_no_second_warm_up_after_a_stop(self):
        p, calls = bare(stop_after=1)

        def warm_up(side):
            calls["games"] += 1
            return {"reached": True, "run": f"{side.key}-warm"}  # side A warmed up; then the tester pressed Stop
        with mock.patch.object(p, "warmed", return_value=None), mock.patch.object(p, "warm_up", side_effect=warm_up):
            out = p.ab("x")
        self.assertEqual(calls["games"], 1)  # side B's warm-up never started
        self.assertEqual(out["stopped"], "stopped by the tester")

    def test_a_stopped_run_is_not_repeated(self):
        p, calls = bare(stop_after=1)

        def timed(side, label, window, warmed_by):
            calls["games"] += 1
            return {"run": label, "side": side.key, "counts": False}
        with mock.patch.object(p, "warmed", return_value="earlier-run"), mock.patch.object(p, "window", return_value=("w", 1, "f")), \
                mock.patch.object(p, "timed", side_effect=timed), mock.patch.object(p, "pairs", return_value=[]):
            out = p.ab("x")
        self.assertEqual(calls["games"], 1)
        self.assertEqual(out["stopped"], "stopped by the tester")


if __name__ == "__main__":
    unittest.main()
