"""The results repository's workflow files: their triggers, and that no step runs code from the results repository."""

import unittest
from pathlib import Path

import helpers  # noqa: F401

from title_runs import ROOT

try:
    import yaml
except ImportError:  # PyYAML is not in the standard library; the check is skipped without it.
    yaml = None

WORKFLOWS = ROOT / "results_repo" / ".github" / "workflows"


@unittest.skipIf(yaml is None, "PyYAML is not installed")
class Workflows(unittest.TestCase):
    def load(self, name):
        data = yaml.safe_load((WORKFLOWS / name).read_text())
        return data, data[True] if True in data else data["on"]

    def steps(self, data):
        (job,) = data["jobs"].values()
        return job["steps"]

    def test_triggers(self):
        _, on = self.load("queue.yml")
        self.assertEqual(set(on), {"repository_dispatch", "schedule", "workflow_dispatch"})
        self.assertEqual(on["repository_dispatch"]["types"], ["anyps5-event"])
        _, on = self.load("publish.yml")
        self.assertEqual(on["push"], {"branches": ["main"], "paths": ["results/**", "claims/**"]})

    def test_code_comes_from_the_pinned_tool_only(self):
        for name in ("queue.yml", "publish.yml"):
            data, _ = self.load(name)
            steps = self.steps(data)
            checkouts = [s for s in steps if s.get("uses", "").startswith("actions/checkout")]
            self.assertEqual([c["with"]["path"] for c in checkouts], ["data", "state", "tool"], name)
            tool = checkouts[2]["with"]
            self.assertEqual((tool["repository"], tool["ref"]), ("${{ vars.TITLE_RUNS_TOOL_REPOSITORY }}", "${{ vars.TITLE_RUNS_TOOL_COMMIT }}"))
            self.assertFalse(checkouts[0]["with"]["persist-credentials"], name)
            runs = [s["run"] for s in steps if "run" in s]
            relay = [r for r in runs if "relay" in r]
            self.assertEqual(len(relay), 1, name)
            self.assertTrue(relay[0].startswith("python3 -I tool/title-runs relay "), name)
            for run in runs:
                self.assertNotIn("data/", run.replace("--data data", ""), name)


if __name__ == "__main__":
    unittest.main()
