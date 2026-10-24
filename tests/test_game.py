"""Starting a game (game.py): the title gets SIGINT, the way stop() asks it to quit, even when title-runs itself was
started with SIGINT ignored (a shell's background job)."""

import signal
import tempfile
import time
import unittest
from pathlib import Path

import helpers  # noqa: F401

from title_runs import game


class Start(unittest.TestCase):
    def test_sigint_is_not_ignored_in_the_game(self):
        folder = Path(tempfile.mkdtemp())
        title = folder / "title"
        title.write_text("#!/bin/sh\ngrep SigIgn /proc/self/status\n")
        title.chmod(0o755)
        before = signal.signal(signal.SIGINT, signal.SIG_IGN)
        try:
            running = game.Game(title, folder, folder, {}, "none", (), ()).start()
        finally:
            signal.signal(signal.SIGINT, before)
        deadline = time.monotonic() + 10
        while running.alive() and time.monotonic() < deadline:
            time.sleep(0.05)
        running.out.close()
        ignored = int((folder / "game.log").read_text().split()[1], 16)
        self.assertFalse(ignored & (1 << (signal.SIGINT - 1)), hex(ignored))


if __name__ == "__main__":
    unittest.main()
