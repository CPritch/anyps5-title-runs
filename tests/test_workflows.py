"""The results repository's one workflow file: its triggers, its one secret, and that it runs nothing from the
results repository itself (the tool at the commit config.json pins)."""

import re
import unittest

import helpers  # noqa: F401

from title_runs import ROOT

try:
    import yaml
except ImportError:  # PyYAML is not in the standard library; the check is skipped without it.
    yaml = None

WORKFLOW = ROOT / "results_repo" / ".github" / "workflows" / "relay.yml"


@unittest.skipIf(yaml is None, "PyYAML is not installed")
class Workflow(unittest.TestCase):
    def setUp(self):
        self.text = WORKFLOW.read_text()
        self.data = yaml.safe_load(self.text)
        (self.job,) = self.data["jobs"].values()

    def test_triggers(self):
        on = self.data[True] if True in self.data else self.data["on"]
        self.assertEqual(set(on), {"schedule", "workflow_dispatch"})
        cron = on["schedule"][0]["cron"]
        self.assertEqual(cron, "2/5 * * * *")  # every 5 minutes from minute 2, in the start/step form GitHub documents

    def test_one_secret(self):
        self.assertEqual(set(re.findall(r"secrets\.([A-Z_]+)", self.text)), {"APP_PRIVATE_KEY"})
        self.assertNotIn("vars.", self.text)

    def test_code_comes_from_the_pinned_tool_only(self):
        steps = self.job["steps"]
        checkouts = [s for s in steps if s.get("uses", "").startswith("actions/checkout")]
        self.assertEqual([c["with"]["path"] for c in checkouts], ["state", "tool"])
        tool = checkouts[1]["with"]
        self.assertEqual((tool["repository"], tool["ref"]), ("${{ steps.config.outputs.tool }}", "${{ steps.config.outputs.commit }}"))
        runs = [s["run"] for s in steps if "run" in s]
        relay = [r for r in runs if "relay poll" in r]
        self.assertEqual(len(relay), 1)
        self.assertTrue(relay[0].startswith("python3 -I tool/title-runs relay poll --state state"))
        self.assertEqual(self.data["permissions"], {"contents": "write", "issues": "write"})


if __name__ == "__main__":
    unittest.main()
