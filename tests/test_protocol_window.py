"""The timed window (protocol.Protocol.window): 60 s, or as many presents as fit a trace of about TRACE_TARGET bytes
at the most bytes per present of the scenario's earlier traces, whichever is fewer, so each trace can be attached."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import helpers  # noqa: F401

from title_runs import protocol


def timed_run(runs_dir, name, presents, size, lines=1):
    """A timed run as the protocol leaves it: its summary line(s) and a trace of size bytes (sparse)."""
    run = Path(runs_dir) / name
    run.mkdir(parents=True)
    rows = [{"trace": "aps5-trace-c49fa17ee046-3.json.gz", "presents": presents}] * lines
    (run / "aps5-summary.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows))
    with open(run / "aps5-trace-c49fa17ee046-3.json.gz", "wb") as trace:
        trace.truncate(size)
    return run


class TracePresents(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

    def test_without_earlier_traces_gta_vs_heaviest(self):
        self.assertEqual(protocol.trace_presents(self.dir),
                         (320, "at most 320 presents fit a 20 MB trace at 61.0 kB per present, with no earlier trace here"))

    def test_the_heaviest_earlier_trace_of_the_scenario(self):
        timed_run(self.dir, "A1", 700, 36_050_000)  # the prologue's heaviest, 51.5 kB per present
        timed_run(self.dir, "B1", 700, 32_300_000)
        timed_run(self.dir, "warm", 700, 90_000_000, lines=0)  # no window line: not a timed run's trace
        timed_run(self.dir, "twice", 700, 90_000_000, lines=2)  # two window lines: not counted, and not read
        self.assertEqual(protocol.trace_presents(self.dir),
                         (380, "at most 380 presents fit a 20 MB trace at 51.5 kB per present, the most of 2 earlier traces here"))

    def test_at_least_100_presents(self):
        timed_run(self.dir, "A1", 100, 40_000_000)
        self.assertEqual(protocol.trace_presents(self.dir)[0], 100)


class Window(unittest.TestCase):
    def protocol(self, runs_dir):
        p = object.__new__(protocol.Protocol)
        p.runs_dir, p.machine_id, p.dump_every = Path(runs_dir), "host-1", 30
        p.sides = [mock.Mock(commit="c" * 40), mock.Mock(commit="0" * 40)]
        return p

    def test_the_window_is_cut_to_fit_the_trace(self):
        runs_dir = Path(tempfile.mkdtemp())
        timed_run(runs_dir, "A1", 700, 36_050_000)
        p = self.protocol(runs_dir)
        with mock.patch.object(protocol, "call", return_value=(0, "3300:700 103 warm-a,warm-b\n")):
            window = p.window()
        self.assertEqual(window, ("3300:380", 103, "warm-a,warm-b"))
        self.assertEqual(p.window_record(window)["sized"], "at most 380 presents fit a 20 MB trace at 51.5 kB per present, the most of 1 earlier trace here")

    def test_60_s_when_that_is_fewer(self):
        runs_dir = Path(tempfile.mkdtemp())
        timed_run(runs_dir, "A1", 3600, 36_000_000)  # 10 kB per present: 2000 would fit, and 60 s at 30 per second is 1800
        with mock.patch.object(protocol, "call", return_value=(0, "1200:1800 35 warm-a\n")):
            self.assertEqual(self.protocol(runs_dir).window()[0], "1200:1800")


if __name__ == "__main__":
    unittest.main()
