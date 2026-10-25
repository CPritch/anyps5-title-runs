"""Two title-runs processes on one computer (the window and the command line): shared files are changed under a lock,
one process runs a test at a time and says who, a stop asked for elsewhere ends this one's test, and a setting the
command line changed while the window was open is neither lost nor undone."""

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

import helpers  # noqa: F401
from helpers import make_config

from title_runs import client as clients, config as configs, configfile, local_tests, locks
from title_runs.engine import Engine

ROOT = Path(__file__).resolve().parent.parent

HOLD = """
import sys, time
sys.path.insert(0, {root!r})
from title_runs import locks
with locks.Runner({state!r}).hold():
    print("held", flush=True)
    time.sleep(30)
"""

ADD = """
import sys
sys.path.insert(0, {root!r})
from title_runs import config as configs, local_tests
local = local_tests.LocalTests(configs.load({config!r}), log=lambda *_: None)
for n in range(25):
    local.change(lambda data: data["entries"].append({{"pr": {base} + n, "status": "queued"}}))
"""


def holding(state_dir):
    """A second process holding the runner lock, once it says so."""
    process = subprocess.Popen([sys.executable, "-I", "-c", HOLD.format(root=str(ROOT), state=str(state_dir))], stdout=subprocess.PIPE, text=True)
    assert process.stdout.readline().strip() == "held"
    return process


class Runner(unittest.TestCase):
    def setUp(self):
        self.state = Path(tempfile.mkdtemp())

    def test_one_test_at_a_time_and_who(self):
        runner = locks.Runner(self.state)
        self.assertIsNone(runner.holder())
        other = holding(self.state)
        try:
            self.assertEqual(runner.holder(), other.pid)
            with self.assertRaisesRegex(locks.Busy, f"another title-runs process \\(pid {other.pid}\\) is running a test"):
                with runner.hold():
                    pass
        finally:
            other.kill()
            other.wait()
            other.stdout.close()
        self.assertIsNone(runner.holder())  # the lock goes with the process, however it ended
        with runner.hold():
            self.assertEqual(runner.holder(), os.getpid())

    def test_a_stop_asked_for_elsewhere_ends_this_test(self):
        status = clients.Status(self.state / "client" / "status.json")
        status.update(stop_requested=True)  # left from the test before: not this one's
        stopped = threading.Event()
        with locks.Runner(self.state).hold(status, stopped.set):
            self.assertFalse(status.read()["stop_requested"])
            time.sleep(1.5)
            self.assertFalse(stopped.is_set())
            status.update(stop_requested=True)  # Stop in the window, or title-runs stop
            self.assertTrue(stopped.wait(3))


class SharedFiles(unittest.TestCase):
    def test_two_processes_change_the_local_tests_list_without_losing_a_change(self):
        config = make_config(local_repository="boykopovar/AnyPS5", local_prs=[1])
        configfile.save(config)
        scripts = [ADD.format(root=str(ROOT), config=str(config.path), base=base) for base in (1000, 2000)]
        processes = [subprocess.Popen([sys.executable, "-I", "-c", script]) for script in scripts]
        for process in processes:
            self.assertEqual(process.wait(timeout=60), 0)
        entries = local_tests.LocalTests(configs.load(config.path), log=lambda *_: None).read()["entries"]
        self.assertEqual(len(entries), 50)


class Config(unittest.TestCase):
    def setUp(self):
        self.config = make_config(local_repository="boykopovar/AnyPS5", local_prs=[4287], testing="off")
        configfile.save(self.config)
        self.engine = Engine(configs.load(self.config.path))

    def test_the_window_takes_what_the_command_line_changed(self):
        time.sleep(0.01)
        configfile.change(self.config.path, lambda c: setattr(c, "testing", "now"))  # title-runs testing now
        self.assertEqual(self.engine.sync_config(), ["testing"])
        self.assertEqual(self.engine.config.testing, "now")
        self.assertEqual(self.engine.work.get_nowait(), ("wake", None))
        self.assertEqual(self.engine.sync_config(), [])  # nothing new

    def test_a_list_change_with_the_switch_reads_the_list_first(self):
        time.sleep(0.01)
        configfile.change(self.config.path, lambda c: (setattr(c, "testing", "now"), c.local_trusted.append("oneandonlydean")))
        self.assertEqual(sorted(self.engine.sync_config()), ["local_trusted", "testing"])
        self.assertEqual(self.engine.work.get_nowait(), ("local", None))  # read again before the next test, not only woken

    def test_a_save_by_the_window_keeps_the_command_lines_change(self):
        configfile.change(self.config.path, lambda c: c.local_prs.append(9289))  # title-runs local add 9289
        self.engine.config.text_size = "large"  # the window's own change, not yet merged
        self.engine.save_config()
        saved = configs.load(self.config.path)
        self.assertEqual((saved.local_prs, saved.text_size), ([4287, 9289], "large"))

    def test_the_windows_own_change_wins_over_the_same_setting_on_disk(self):
        configfile.change(self.config.path, lambda c: setattr(c, "testing", "now"))
        self.engine.config.testing = "schedule"  # switched in the window at the same moment, from off
        self.engine.save_config()
        self.assertEqual(configs.load(self.config.path).testing, "schedule")


if __name__ == "__main__":
    unittest.main()
