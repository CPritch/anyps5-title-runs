"""The command line (cli.py): every command says what it does, what it changes and what it prints, docs/CLI.md is
what the commands say, the exit codes, the JSON, and the commands themselves on a config of their own."""

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

import helpers  # noqa: F401
from helpers import make_config

from title_runs import cli, client as clients, config as configs, configfile, local_tests

ROOT = Path(__file__).resolve().parent.parent
HEAD = "7aea3fe29ff7b0c4240363ab722e12265439bb1f"


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = cli.main(list(argv))
    return code, out.getvalue(), err.getvalue()


class Help(unittest.TestCase):
    def test_every_command_says_what_it_does_changes_and_prints(self):
        code, overview, _ = run()
        self.assertEqual(code, 0)
        for command in cli.COMMANDS:
            if command.hidden:
                continue
            with self.subTest(command.name):
                self.assertIn(f"  {command.name} ", overview)
                code, text, _ = run("help", *command.path)
                self.assertEqual(code, 0)
                self.assertIn("Changes: ", text)
                self.assertIn("Examples:", text)
                if not command.passthrough:
                    self.assertIn(command.summary.split(":")[0], text)
                    self.assertIn("JSON (--json): ", text)
                    self.assertEqual(run(*command.path, "--help")[1], text)

    def test_nothing_writes_to_github(self):
        for command in cli.COMMANDS:
            self.assertNotIn("GitHub as you", command.changes, command.name)
        self.assertIn("No command posts anything or writes to GitHub", cli.overview())

    def test_a_group_alone_lists_its_commands(self):
        code, text, _ = run("local", "--help")
        self.assertEqual(code, 0)
        self.assertIn("title-runs local alone is title-runs local list", text)
        self.assertIn("  local posted ", text)
        self.assertEqual(run("help", "local")[1], text)

    def test_the_docs_are_what_the_commands_say(self):
        self.assertEqual((ROOT / "docs" / "CLI.md").read_text(), cli.markdown(),
                         "docs/CLI.md is out of date: title-runs help --markdown > docs/CLI.md")

    def test_a_command_written_wrong_is_exit_2(self):
        self.assertEqual(run("local", "nope")[0], 2)
        self.assertEqual(run("testing", "sometimes")[0], 2)
        self.assertEqual(run("help", "nope")[0], 2)


class Commands(unittest.TestCase):
    def setUp(self):
        config = make_config(local_repository="boykopovar/AnyPS5", local_prs=[4287], testing="off")
        configfile.save(config)
        self.path = config.path
        self.state = config.state_dir

    def cli(self, *argv):
        return run("--config", str(self.path), *argv)

    def json(self, *argv):
        """The exit code and the JSON printed: the last object, for run, which prints one per line."""
        code, out, err = run("--json", "--config", str(self.path), *argv)
        return code, json.loads(out if argv[:1] != ("run",) else out.splitlines()[-1])

    def config(self):
        return configs.load(self.path)

    def tested(self, pr=4287, posted=None):
        """A local result for pr, with its report as written when it ran."""
        draft = self.state / "local-tests" / "drafts" / f"{pr}.md"
        draft.parent.mkdir(parents=True, exist_ok=True)
        draft.write_text("Ran this on Grand Theft Auto V (PPSA04263 01.010.002) ...\n")
        entry = {"pr": pr, "head": HEAD, "title": "perf(shader): pick", "author": "karanvora2599", "added": "2026-10-23T15:00:00Z", "status": "done",
                 "at": "2026-10-23T16:38:00Z", "main": "1" * 40, "job": f"{pr}-x", "verdict": "Faster (-5.11 ms, -6.8 %)", "draft": str(draft)}
        if posted:
            entry["posted"] = posted
        local = local_tests.LocalTests(self.config(), log=lambda *_: None)
        local.write({"repository": "boykopovar/AnyPS5", "pinned": None, "entries": [entry]})

    def test_the_testing_switch(self):
        self.assertEqual(self.cli("testing"), (0, "Testing is off.\n", ""))
        self.assertEqual(self.cli("testing", "now")[0], 0)
        self.assertEqual(self.config().testing, "now")
        self.assertEqual(self.json("testing")[1]["testing"], "now")

    def test_stop_ends_the_test_wherever_it_runs_and_switches_testing_off(self):
        configfile.change(self.path, lambda c: setattr(c, "testing", "schedule"))
        code, data = self.json("stop")
        self.assertEqual((code, data), (0, {"stopped": None, "testing": "off"}))
        self.assertTrue(clients.Status(self.state / "client" / "status.json").read()["stop_requested"])
        self.assertEqual(self.config().testing, "off")

    def test_local_tests_list_add_remove_follow_and_fixes(self):
        code, data = self.json("local", "add", "9289", "https://github.com/boykopovar/AnyPS5/pull/9287/files")
        self.assertEqual((code, data), (0, {"added": [9289, 9287]}))
        self.assertEqual(self.config().local_prs, [4287, 9289, 9287])
        self.assertEqual(self.cli("local", "remove", "#9289")[0], 0)
        self.assertEqual(self.config().local_prs, [4287, 9287])
        self.cli("local", "follow", "Celegans12")
        self.cli("local", "fixes", "9730")
        self.assertEqual((self.config().local_people, self.config().local_fixes), (["Celegans12"], [9730]))
        self.cli("local", "unfollow", "Celegans12")
        self.cli("local", "fixes", "--none")
        self.assertEqual((self.config().local_people, self.config().local_fixes), ([], []))
        self.assertEqual(self.json("local")[1]["repository"], "boykopovar/AnyPS5")
        code, out, err = self.cli("local", "add", "the voice one")
        self.assertEqual(code, 1)
        self.assertTrue(err.startswith("title-runs: "), err)
        self.assertEqual(self.cli("local", "add", "https://github.com/someone/else/pull/12")[0], 1)  # not the project's
        self.assertEqual(self.config().local_prs, [4287, 9287])

    def test_a_report_has_the_link_first_and_posting_is_only_recorded(self):
        self.tested()
        code, out, _ = self.cli("local", "report", "4287")
        self.assertEqual(code, 0)
        self.assertEqual(out.splitlines()[0], "Post it on https://github.com/boykopovar/AnyPS5/pull/4287")
        self.assertIn("Ran this on Grand Theft Auto V", out)
        self.assertEqual(self.cli("local", "report", "4287", "--text")[1], "Ran this on Grand Theft Auto V (PPSA04263 01.010.002) ...\n")
        code, data = self.json("local", "report", "4287")
        self.assertEqual((data["link"], data["posted"], data["traces"]), ("https://github.com/boykopovar/AnyPS5/pull/4287", False, []))
        self.assertEqual(self.json("local", "posted", "4287"), (0, {"pr": 4287, "head": HEAD, "posted": True}))
        self.assertEqual(self.json("local")[1]["prs"][0]["report"], "Posted")
        self.assertEqual(self.json("local", "posted", "4287", "--undo")[1]["posted"], False)

    def test_what_couldnt_be_done_is_exit_1_with_why(self):
        self.assertEqual(self.json("local", "report", "9999"), (1, {"error": "#9999 has no local result yet (title-runs local list)."}))
        self.tested()
        self.assertEqual(self.json("local", "report", "4287", "--test", "3"), (1, {"error": "#4287 has 1 result; --test takes 1 to 1."}))
        code, out, err = run("--config", str(self.path.parent / "missing.toml"), "status")
        self.assertEqual(code, 1)
        self.assertIn("No config at", err)

    def test_status_says_what_this_computer_does(self):
        code, data = self.json("status")
        self.assertEqual(code, 0)
        for key in ("headline", "kind", "testing", "running", "busy_elsewhere", "next", "notes", "machine", "project", "config", "state"):
            self.assertIn(key, data)
        self.assertEqual((data["kind"], data["running"], data["project"]), ("setup", None, "boykopovar/AnyPS5"))
        self.assertEqual(self.cli("status")[1].splitlines()[0], "Almost ready. Go through the first-run steps.")
        # the walkthrough done: nothing left to set up
        clients.Client(self.config(), log=lambda *_: None).finish_onboarding({"idle": "hours"})
        lines = self.cli("status")[1].splitlines()
        self.assertEqual(lines[:2], ["Nothing to test. When a pull request on your list gets new commits, they're tested next.",
                                     "Testing is off."])

    def test_run_once_starts_one_test_whatever_the_switch_says(self):
        self.assertEqual(self.json("run", "--once")[1]["error"], "Go through the first-run steps first (title-runs window). Nothing runs before then.")
        clients.Client(self.config(), log=lambda *_: None).finish_onboarding({"idle": "hours"})
        with mock.patch("title_runs.engine.Engine.refresh_local") as refresh, \
                mock.patch("title_runs.engine.Engine.next_test", return_value="tested #4287 (a local test)") as next_test:
            code, out, _ = self.cli("run", "--once")
        self.assertEqual((code, out), (0, "tested #4287 (a local test)\n"))
        refresh.assert_called_once_with(force=True)
        next_test.assert_called_once_with(now=True)

    def test_a_scenario_is_one_of_the_games_own(self):
        code, data = self.json("games", "scenario", "PPSA04263")
        self.assertEqual((code, data["chosen"]), (0, ["prologue"]))
        both = self.json("games", "scenario", "PPSA04263", "franklins-house", "prologue")[1]["chosen"]
        self.assertEqual(both, ["franklins-house", "prologue"])
        self.assertEqual(self.config().titles["PPSA04263"].scenarios, ["franklins-house", "prologue"])
        self.assertEqual(self.json("games", "scenario", "PPSA04263", "prologue", "the-moon")[0], 1)
        self.assertEqual(self.config().titles["PPSA04263"].scenarios, ["franklins-house", "prologue"])  # unchanged


if __name__ == "__main__":
    unittest.main()
