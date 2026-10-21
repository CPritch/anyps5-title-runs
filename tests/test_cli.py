import argparse
import json
import tempfile
import unittest
from pathlib import Path

from helpers import make_config

from title_runs import cli
from title_runs.state import PAUSED, READY, State


class Publish(unittest.TestCase):
    def setUp(self):
        self.config = make_config()
        self.state = State(self.config.state_dir / "state.json")
        self.results = Path(tempfile.mkdtemp()) / "results.json"
        self.results.write_text(json.dumps({"pr": 10, "head": "h1", "status": "done", "titles": {}, "sandbox": "bwrap"}))

    def publish(self, status):
        self.state.pr(10)["heads"].append({"head": "h1", "status": status, "seen": "2026-10-20T00:00:00Z", "trust": "author mallory is not on the allowlist"})
        self.state.save()
        cli.cmd_publish(self.config, argparse.Namespace(pr=10, results=self.results, post=False))
        return State(self.config.state_dir / "state.json")

    def test_a_paused_head_is_not_published(self):
        with self.assertRaises(SystemExit) as raised:
            self.publish(PAUSED)
        self.assertIn("only a ready head's results are published", str(raised.exception))
        self.assertFalse((self.config.state_dir / "outbox").exists())

    def test_a_ready_head_is_published_to_the_outbox(self):
        state = self.publish(READY)
        self.assertEqual(state.current(10)["status"], "done")
        self.assertEqual([p["action"] for p in state.pr(10)["comment_posts"]], ["new"])
        self.assertEqual(len(list((self.config.state_dir / "outbox" / "10").glob("*.md"))), 1)


if __name__ == "__main__":
    unittest.main()
