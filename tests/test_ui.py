"""The window's model (no Qt), and the trust dialog's rules (offscreen Qt): Run anyway needs a scope, the box ticked and
the author's name typed exactly; Enter does not accept."""

import datetime
import json
import os
import unittest
from pathlib import Path

import helpers  # noqa: F401

from title_runs import formats
from title_runs.ui import model

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
try:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtCore import QEvent
    from PySide6.QtWidgets import QApplication
except ImportError:  # the window needs PySide6; the model does not
    QApplication = None

HEAD = "69ac2e155ad018ed1fb9028d2028d15999a8571e"


def listed(number, title="t", body="", labels=(), author="someuser", draft=False, state="OPEN"):
    return {"number": number, "title": title, "body": body, "state": state, "isDraft": draft, "author": {"login": author}, "headRefOid": HEAD,
            "labels": {"nodes": [{"name": n} for n in labels]}}


class Model(unittest.TestCase):
    def test_four_sections(self):
        prs = [listed(8104, labels=["perf"]), listed(6488, body="- [x] Unblocks: PPSA04263"), listed(7000, labels=["agc"]), listed(7001),
               listed(7002, draft=True), listed(7003, state="CLOSED")]
        queue = {"entries": [{"pr": 8104, "head": HEAD, "priority": "high", "titles": ["PPSA04263"], "unapproved": [{"sha": "1" * 40}]}]}
        sections = model.pr_sections(prs, queue, {"PPSA04263": "GTA V"})
        self.assertEqual([[r["number"] for r in sections[name]] for name in model.SECTIONS], [[8104], [6488], [7000], [7001]])
        queued = sections[model.SECTIONS[0]][0]
        self.assertEqual((queued["priority"], queued["titles"], queued["run"]), ("high", "GTA V", False))
        self.assertIn("1 push not checked", queued["badge"])
        mention = sections[model.SECTIONS[1]][0]
        self.assertEqual((mention["titles"], mention["badge"], mention["run"]), ("Unblocks PPSA04263", "⚠ not checked", True))

    def test_search(self):
        sections = model.pr_sections([listed(1, "perf: fast"), listed(2, "fix: slow")], {"entries": []}, {}, "fast")
        self.assertEqual(sum(len(v) for v in sections.values()), 1)

    def test_tray_states(self):
        view = {"running": None, "up_next": [], "recent": []}
        self.assertEqual(model.tray_view({"state": "idle", "line": "Idle"}, view, [], "schedule")[0], "idle")
        self.assertEqual(model.tray_view({"state": "idle", "line": "Idle"}, view, [{"number": 1}], "schedule"), ("waiting", ["Idle", "1 PR waiting for you"]))
        self.assertEqual(model.tray_view({"state": "idle", "line": "Idle"}, view, [], "off")[1], ["Idle", "Testing is off: no test starts."])
        self.assertEqual(model.tray_view({"state": "error", "line": "Error: build failed"}, view, [], "schedule")[0], "error")
        running = {"running": {"number": 8104}, "up_next": [{"number": 7922, "score": 4, "titles": "GTA V", "priority": "high"}], "recent": []}
        state, lines = model.tray_view({"state": "running", "line": "Running: #8104 · PPSA04263 · main run 2/4"}, running, [], "schedule")
        self.assertEqual((state, lines), ("running", ["Running: #8104 · PPSA04263 · main run 2/4", "Next: #7922 · GTA V (high)"]))


@unittest.skipIf(QApplication is None, "PySide6 is not installed")
class TrustDialogRules(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_run_anyway_needs_all_three(self):
        from title_runs.ui.trust_dialog import TrustDialog
        dialog = TrustDialog(8123, "perf(agc): something", "someuser")
        self.assertFalse(dialog.run.isEnabled())
        dialog.group.button(0).setChecked(True)
        dialog.update_run()
        self.assertFalse(dialog.run.isEnabled())
        dialog.understood.setChecked(True)
        dialog.typed.setText("SomeUser")
        self.assertFalse(dialog.run.isEnabled())
        dialog.typed.setText("someuser")
        self.assertTrue(dialog.run.isEnabled())
        dialog.run.click()
        self.assertEqual((dialog.result(), dialog.scope), (TrustDialog.Accepted, "head"))

    def test_enter_does_not_accept(self):
        from title_runs.ui.trust_dialog import TrustDialog
        dialog = TrustDialog(8123, "perf(agc): something", "someuser")
        dialog.group.button(2).setChecked(True)
        dialog.understood.setChecked(True)
        dialog.typed.setText("someuser")
        dialog.show()
        for key in (Qt.Key_Return, Qt.Key_Enter):
            QApplication.sendEvent(dialog.typed, QKeyEvent(QEvent.KeyPress, key, Qt.NoModifier))
            QApplication.sendEvent(dialog, QKeyEvent(QEvent.KeyPress, key, Qt.NoModifier))
        self.assertTrue(dialog.isVisible())
        self.assertIsNone(dialog.scope)
        self.assertFalse(dialog.run.isDefault() or dialog.cancel.isDefault())
        dialog.close()


if __name__ == "__main__":
    unittest.main()


@unittest.skipIf(QApplication is None, "PySide6 is not installed")
class WalkthroughAndOverview(unittest.TestCase):
    """The walkthrough's gates (the sandbox page needs its box ticked; without idle detection, hours; sign-in), Finish
    marking it done, and the Overview tab: a pending registration, Approve only for maintainers, approval by label."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        import tempfile
        from pathlib import Path
        from unittest import mock

        from relay_helpers import History
        from title_runs import standin
        from title_runs.ui import app

        self.root = Path(tempfile.mkdtemp())
        history = History(self.root)
        self.stand = standin.create(self.root / "standin", ["CPritch"], history.dir, history.m2,
                                    [{"number": 8104, "title": "perf(agc): stage", "author": "Celegans12", "head": history.A, "head_ref": "perf/staging"}],
                                    {"CPritch": "admin", "Celegans12": "read"})
        dumps = self.root / "dumps" / "PPSA04263-app"
        (dumps / "sce_sys").mkdir(parents=True)
        (dumps / "eboot.bin").write_bytes(b"")
        (dumps / "sce_sys" / "param.json").write_text('{"titleId": "PPSA04263", "contentVersion": "01.010.002", '
                                                       '"localizedParameters": {"defaultLanguage": "en-US", "en-US": {"titleName": "Grand Theft Auto V"}}}')
        (history.dir / "CMakeLists.txt").write_text("")
        self.dumps = self.root / "dumps"
        self.config_path = self.root / "tester.toml"
        app.new_config(self.config_path, str(self.stand.results_git), self.stand.endpoint, self.root / "state")
        text = self.config_path.read_text().replace("[results]", f'[source]\nrepo_dir = "{history.dir}"\n\n[results]')
        self.config_path.write_text(text)
        from title_runs import config as configs
        self.patch = mock.patch("title_runs.platform_info.idle_detection", return_value=(False, "Hyprland does not tell logind"))
        self.patch.start()
        self.engine = app.Engine(configs.load(self.config_path))
        self.engine.client.info = {"gpu": "NVIDIA GeForce RTX 5060 Laptop GPU", "driver": "NVIDIA 615.71.09", "os": "Linux 7.2.8"}
        self.engine.client.repo.sync()

    def tearDown(self):
        self.patch.stop()

    def test_walkthrough_gates_and_finish(self):
        from title_runs.ui.walkthrough import Walkthrough
        wizard = Walkthrough(self.engine, str(self.dumps))
        wizard.show()
        self.assertFalse(wizard.sandbox.isComplete())
        wizard.sandbox.read.setChecked(True)
        self.assertTrue(wizard.sandbox.isComplete())
        self.assertFalse(wizard.when.idle.isEnabled())
        self.assertEqual((wizard.when.first.value(), wizard.when.last.value()), (1, 7))
        wizard.when.last.setValue(1)
        self.assertFalse(wizard.when.isComplete())
        wizard.when.last.setValue(7)
        self.assertTrue(wizard.dumps.isComplete())
        self.assertFalse(wizard.sign_in.isComplete())
        wizard.sign_in.start()
        self.stand.authorize(wizard.sign_in.device["user_code"], "standin-tester")
        wizard.sign_in.poll()
        self.assertTrue(wizard.sign_in.isComplete())
        self.assertFalse(self.engine.client.onboarded())
        self.assertEqual(self.engine.readiness()[0], False)
        wizard.register_page.register()
        self.assertEqual(self.engine.client.registration()[0], "pending")
        wizard.accept()
        self.assertTrue(self.engine.client.onboarded())
        self.assertEqual(self.engine.config.schedule["hours"], [1, 7])
        self.assertFalse(self.engine.config.schedule["idle_only"])
        self.assertEqual(list(self.engine.config.titles), ["PPSA04263"])
        self.assertEqual(self.engine.readiness()[:2], (False, "waiting for a maintainer to approve this machine"))

    def test_the_sign_in_page_slows_down_when_github_says_so(self):
        from unittest import mock
        from title_runs.ui.walkthrough import Walkthrough
        wizard = Walkthrough(self.engine, str(self.dumps))
        page = wizard.sign_in
        page.start()
        self.assertEqual(page.timer.interval(), (page.device["interval"] + 1) * 1000)

        def slow_down(device):
            device["interval"] = 10
            return None
        with mock.patch.object(self.engine.client.flow(), "poll", side_effect=slow_down):
            page.poll()
        self.assertEqual(page.timer.interval(), 11000)
        self.assertTrue(page.timer.isActive())

    def test_the_testing_switch(self):
        import types
        from unittest import mock
        from title_runs import config as configs
        engine = self.engine
        job = types.SimpleNamespace(entry={"pr": 8104, "head": HEAD, "title": "t", "author": "a", "job": "8104-x"})
        with mock.patch.object(engine.client, "ready", return_value=(True, "")), \
                mock.patch.object(engine.client, "allowed_now", return_value=(False, "outside the hours 01-07")), \
                mock.patch.object(engine.client, "run") as run:
            engine.config.testing = "schedule"
            with mock.patch.object(engine.client, "next_job", return_value=job):
                self.assertEqual(engine.next_test(), "outside the hours 01-07")
                run.assert_not_called()
                engine.set_testing("now")  # whatever the hours
                self.assertEqual(engine.next_test(), "ran 8104-x")
                run.assert_called_once()
            with mock.patch.object(engine.client, "next_job", return_value=None):
                self.assertEqual(engine.next_test(), "nothing to test")
        with mock.patch("title_runs.platform_info.stop_children", return_value=0):
            engine.stop()  # ends the test and switches testing off
        self.assertEqual(configs.load(self.config_path).testing, "off")
        with self.assertRaises(ValueError):
            engine.set_testing("sometimes")
        engine.client.status.update(paused_until="indefinitely")  # the tray's Pause before the switch
        engine.set_testing("schedule")
        engine.adopt_old_pause()
        self.assertEqual((engine.config.testing, engine.status().get("paused_until")), ("off", None))
        old = self.root / "old.toml"
        old.write_text(f'state_dir = "{self.root / "state"}"\n[client]\nautomatic = false\n')
        self.assertEqual(configs.load(old).testing, "off")
        old.write_text(f'state_dir = "{self.root / "state"}"\n')
        self.assertEqual(configs.load(old).testing, "schedule")

    def test_overview_approve_is_for_maintainers(self):
        from title_runs.ui.window import MainWindow
        self.engine.client.finish_onboarding({})
        flow = self.engine.client.flow()
        device = flow.start()
        self.stand.authorize(device["user_code"], "standin-tester")
        flow.poll(device)
        issue = self.engine.client.register()
        self.stand.tick()
        self.engine.load(sync=True)
        from title_runs.ui.maintainer import MaintainerWindow
        window = MaintainerWindow(self.engine)
        window.overview.refresh()
        self.assertEqual(window.overview.pending.topLevelItemCount(), 1)
        buttons = window.overview.pending.itemWidget(window.overview.pending.topLevelItem(0), 3)
        approve = buttons.layout().itemAt(0).widget()
        self.assertFalse(approve.isEnabled())
        self.assertEqual(self.engine.decide_registration(issue, "approved"), "Only a maintainer can approve or decline machines.")
        flow.sign_out()
        device = flow.start()
        self.stand.authorize(device["user_code"], "CPritch")
        flow.poll(device)
        window.overview.refresh()
        approve = window.overview.pending.itemWidget(window.overview.pending.topLevelItem(0), 3).layout().itemAt(0).widget()
        self.assertTrue(approve.isEnabled())
        approve.click()
        self.assertEqual(window.overview.pending.topLevelItem(0).text(3), "approved: next workflow run")
        self.stand.tick()
        self.engine.load(sync=True)
        window.overview.refresh()
        self.assertEqual(window.overview.pending.topLevelItemCount(), 0)
        self.assertEqual(window.overview.machines.topLevelItem(0).text(0), "standin-tester/" + self.engine.config.machine)
        self.assertEqual(window.overview.machines.topLevelItem(0).text(3), "@CPritch")

    def test_settings_switch_the_results_repository(self):
        from title_runs import standin
        from title_runs.ui.window import MainWindow
        from relay_helpers import History
        (self.root / "h2").mkdir()
        history = History(self.root / "h2")
        other = standin.create(self.root / "moved", ["maintainer2"], history.dir, history.m2, [], {"maintainer2": "admin"},
                               client_id="Iv1.maintainers-app", results="maintainer2/results")
        window = MainWindow(self.engine)
        window.settings.account.url.setText(str(other.results_git))
        window.settings.account.save()
        self.assertEqual(self.engine.client.results_repository(), "maintainer2/results")
        self.assertIn("Now using maintainer2/results.", window.settings.account.check_label.text())
        self.assertIn(f'url = "{other.results_git}"', self.config_path.read_text())

    def test_an_ignored_comment_shows_in_the_overview_and_to_its_tester(self):
        from title_runs import formats, standin
        from title_runs.ui.window import MainWindow
        self.engine.client.finish_onboarding({})
        flow = self.engine.client.flow()
        device = flow.start()
        self.stand.authorize(device["user_code"], "standin-tester")
        flow.poll(device)
        self.stand.tick()
        trust = self.engine.client.repo.cursors().get("tester_trust_issue") or json.loads(
            standin.git(self.stand.results_git, "show", "main:cursors.json"))["tester_trust_issue"]
        self.engine.client.github().create_comment(trust, formats.payload_body("result", {"machine": "laptop", "job": "x"}, "a result."))
        self.stand.tick()
        self.engine.load(sync=True)
        from title_runs.ui.maintainer import MaintainerWindow
        tools = MaintainerWindow(self.engine)
        tools.refresh()
        self.assertIn("1 comment from an account without a registered machine", tools.overview.ignored.text())
        window = MainWindow(self.engine)
        window.refresh()
        self.assertIn("Your last report wasn't accepted", window.home.notice.text())

    def test_a_new_tester_names_the_results_repository_in_the_walkthrough(self):
        from title_runs import config as configs
        from title_runs.ui import app
        from title_runs.ui.walkthrough import Walkthrough
        fresh = self.root / "fresh" / "config.toml"
        app.new_config(fresh, "", self.stand.endpoint, self.root / "fresh-state")
        engine = app.Engine(configs.load(fresh))
        self.assertEqual(engine.config.results_url, "")
        wizard = Walkthrough(engine, str(self.dumps))  # kept: its pages go with it
        page = wizard.sign_in
        self.assertTrue(page.where.isVisibleTo(page))
        self.assertFalse(page.start_button.isEnabled())
        page.location.setText(str(self.stand.results_git))
        page.use()
        self.assertTrue(page.start_button.isEnabled())
        self.assertIn(f'url = "{self.stand.results_git}"', fresh.read_text())

    def test_find_games_however_the_folder_is_given(self):
        from unittest import mock
        from title_runs.ui.walkthrough import Walkthrough
        wizard = Walkthrough(self.engine, "")
        page = wizard.dumps
        for given in (f" {self.dumps} ", f"file://{self.dumps}", str(self.dumps / "PPSA04263-app")):
            page.folder.setText(given)
            page.scan()
            self.assertEqual([d["title_id"] for d in page.found], ["PPSA04263"], given)
            self.assertIn("Found 1 game in", page.result.text())
        page.folder.setText("")
        with mock.patch("pathlib.Path.home", return_value=self.root):
            page.scan()  # nothing given: the home folder
        self.assertEqual([d["title_id"] for d in page.found], ["PPSA04263"])
        page.folder.setText(str(self.root / "nothing-here"))
        page.scan()
        self.assertIn("There is no folder", page.result.text())
        self.assertFalse(page.isComplete())

    def test_the_clients_own_copies_are_not_games_again(self):
        import shutil
        from title_runs import platform_info
        copy = Path(self.engine.config.state_dir) / "games" / "PPSA04263" / "main"
        shutil.copytree(self.dumps / "PPSA04263-app", copy)
        shutil.copytree(self.dumps / "PPSA04263-app", self.root / "dumps-too" / "PPSA04263-app")
        found = platform_info.find_dumps(self.root, depth=5, skip=[self.engine.config.state_dir])
        self.assertEqual(len(found), 1)  # the same title and version once, and never from the state folder
        self.assertNotIn(str(Path(self.engine.config.state_dir)), found[0]["path"])

    def test_owner_name_in_the_config_is_github(self):
        from title_runs import config as configs
        path = self.root / "owner-name.toml"
        path.write_text('[results]\nurl = "CPritch/anyps5-title-runs-results"\n')
        self.assertEqual(configs.load(path).results_url, "https://github.com/CPritch/anyps5-title-runs-results.git")

    def test_the_listing_is_of_the_results_repositorys_repository(self):
        from unittest import mock
        from title_runs import poller
        self.engine.load(sync=True)
        self.assertEqual(self.engine.repository, "CPritch/AnyPS5")
        other = poller.Listing.of(self.engine.config.state_dir, "boykopovar/AnyPS5")
        other.data["prs"]["6321"] = {"number": 6321}
        other.save()
        self.assertEqual(self.engine.listing(), [])  # another repository's listing is not shown
        self.assertEqual(self.engine.listing_note(), "Pull requests of CPritch/AnyPS5: not listed yet")
        pages = {"repository": {"pullRequests": {"nodes": [], "pageInfo": {"hasNextPage": False, "endCursor": None}}}}
        with mock.patch.object(self.engine.client, "tester", return_value="standin-tester"), \
                mock.patch("title_runs.github.GraphQL.query", return_value=pages) as query:
            self.engine.refresh_listing()
            self.engine.refresh_listing()  # fresh: not listed again
        self.assertEqual(query.call_count, 1)
        self.assertEqual(query.call_args[0][1]["owner"], "CPritch")
        self.assertIn("Pull requests of CPritch/AnyPS5, listed", self.engine.listing_note())

    def test_a_maintainers_app_starts_a_stale_relay(self):
        from unittest import mock
        stale = {"last_run": "2026-10-21T20:00:00Z"}
        with mock.patch.object(self.engine.client, "maintainer", return_value=True), \
                mock.patch.object(self.engine.client.repo, "cursors", return_value=stale), \
                mock.patch("title_runs.gh.GitHubRepo.dispatch", side_effect=RuntimeError("403")), \
                mock.patch("subprocess.run", return_value=mock.Mock(returncode=0, stderr="")) as run:
            now = formats.parse_time("2026-10-21T20:10:00Z")
            self.assertEqual(self.engine.keep_relay_going(now), "gh")
            self.assertEqual(self.engine.keep_relay_going(now + datetime.timedelta(minutes=2)), None)  # not again within 5 minutes
            self.assertEqual(self.engine.keep_relay_going(now + datetime.timedelta(minutes=6)), "gh")
        self.assertEqual(run.call_args[0][0][:3], ["gh", "workflow", "run"])
        with mock.patch.object(self.engine.client, "maintainer", return_value=False):
            self.assertIsNone(self.engine.keep_relay_going(now + datetime.timedelta(hours=1)))  # testers never do

    def test_a_note_on_a_registration_taken_since_is_not_shown(self):
        from unittest import mock
        from title_runs import formats
        self.engine.client.finish_onboarding({})
        flow = self.engine.client.flow()
        device = flow.start()
        self.stand.authorize(device["user_code"], "standin-tester")
        flow.poll(device)
        issue = self.engine.client.register()
        self.stand.tick()
        self.engine.load(sync=True)
        stale = {"ignored": {"counts": {"registration": 1}, "recent": [
            {"at": "2026-10-21T19:23:30Z", "issue": issue, "user": "standin-tester", "reason": "registration", "detail": "not in the expected form"}]}}
        with mock.patch.object(self.engine.client.repo, "cursors", return_value=stale), \
                mock.patch("title_runs.formats.now", return_value=formats.parse_time("2026-10-21T20:00:00Z")):
            self.assertEqual(self.engine.ignored_mine(), "")  # the registration is pending now: the note is history
            stale["ignored"]["recent"][0]["issue"] = issue + 100
            self.assertIn("wasn't accepted", self.engine.ignored_mine())
        with mock.patch.object(self.engine.client.repo, "cursors", return_value=stale), \
                mock.patch("title_runs.formats.now", return_value=formats.parse_time("2026-10-23T20:00:00Z")):
            self.assertEqual(self.engine.ignored_mine(), "")  # more than a day old


@unittest.skipIf(QApplication is None, "PySide6 is not installed")
class RowListFill(unittest.TestCase):
    """Enough rows to need a scrollbar: the scrollbar resizes the list while rows are added, before their labels are
    set (this flickered between one row and many in the first overnight run)."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_many_rows_fill_in_a_small_list(self):
        from title_runs.ui.home import RowList
        view = RowList()
        view.resize(400, 120)
        view.show()
        rows = [f"<b>#{n}</b> a change with a long enough title to wrap onto a second line here" for n in range(18)]
        view.set_rows(rows)
        self.app.processEvents()
        self.assertEqual(view.count(), 18)
        self.assertTrue(all(view.itemWidget(view.item(i)) is not None for i in range(18)))
        first = view.item(0)
        view.set_rows(rows)  # the same rows again: nothing rebuilt
        self.assertIs(view.item(0), first)


class MainScreenModel(unittest.TestCase):
    """ui/home.py's words (model.header, step, waiting_for): what a tester reads on the main screen."""

    def test_the_schedule_in_words(self):
        rules = {"hours": [1, 7], "idle_only": True, "idle_minutes": 10, "mains_only": True, "pause_fullscreen": True}
        self.assertEqual(model.schedule_words(rules, idle_detectable=False),
                         "between 01:00 and 07:00, when the computer is plugged in and nothing is fullscreen")
        self.assertEqual(model.schedule_words({**rules, "hours": [0, 24], "mains_only": False}), "when you've been away for 10 minutes and nothing is fullscreen")
        self.assertEqual(model.schedule_words({"hours": [0, 24], "idle_only": False, "mains_only": False, "pause_fullscreen": False}), "at any time")

    def test_the_step_from_the_jobs_progress(self):
        for progress, index in (("starting", 0), ("#1: 69ac2e155 merged onto main d97361bd0 as f0a2a25b4", 0), ("A: building d97361bd0", 1),
                                ("B: built in 29 s", 2), ("PR warm-up", 3), ("main run 1, 1/4", 4), ("PR run 1, 2/4", 5),
                                ("main run 2, 3/4", 6), ("PR run 2, 4/4", 7)):
            self.assertEqual(model.step(progress), index, progress)

    def test_the_team_is_named_by_the_config(self):
        from title_runs.ui import words
        try:
            words.set_team("CPritch")
            self.assertEqual(model.header({}, True, "", "schedule", True, "", None)["detail"], "New tests from CPritch show up here by themselves.")
            self.assertEqual(model.setup_text("waiting for a maintainer to approve this machine"),
                             "CPritch still has to approve this machine. Nothing to do but wait.")
            words.set_team("the AnyPS5 team")
            self.assertEqual(words.Team(), "The AnyPS5 team")
            words.set_team("")
            self.assertEqual(words.team(), "whoever runs this testing")
        finally:
            words.set_team(None)

    def test_header_states(self):
        best = {"number": 1}
        running = {"state": "running", "job": {"pr": 1, "title": "perf: x"}, "progress": "PR run 1, 2/4"}
        self.assertEqual(model.header(running, True, "", "schedule", True, "", best)["detail"], "Run 2 of 4: with the change")
        self.assertEqual(model.header(running, True, "", "off", True, "", best)["kind"], "running")  # Off starts nothing; Stop ends a test
        self.assertEqual(model.header({}, False, "not signed in", "schedule", True, "", best)["detail"], "Sign in with GitHub.")
        self.assertEqual(model.header({}, True, "", "schedule", True, "", None)["kind"], "idle")
        self.assertEqual(model.header({}, True, "", "off", True, "", best)["kind"], "off")
        waiting = model.header({}, True, "", "schedule", False, "outside the hours 01-07", best)
        self.assertEqual(waiting["detail"], "The next test starts by itself between 01:00 and 07:00, the hours you chose.")
        self.assertEqual(model.header({}, True, "", "now", False, "outside the hours 01-07", best)["kind"], "ready")  # Now: whatever the hours
        self.assertEqual(model.waiting_for("on battery"), "the computer is plugged in")
        self.assertEqual(model.waiting_for("gtav.elf is running"), "gtav.elf has closed")


@unittest.skipIf(QApplication is None, "needs PySide6")
class GameViewFinding(unittest.TestCase):
    """The game's window is found by its class (the title ID), whenever it opened: on 2026-10-22 the view missed every
    run of a test because the window opened before the view took its list of windows, and XWayland gave each later
    run's window the same ID."""

    class FakeX11:
        def __init__(self):
            self.windows = {}  # id: (name, classes)

        def children(self, window=None):
            return list(self.windows)

        def name(self, window):
            return self.windows.get(window, ("", set()))[0]

        def classes(self, window):
            return self.windows.get(window, ("", set()))[1]

        def exists(self, window):
            return window in self.windows

    def view(self):
        from title_runs.ui.gameview import GameView
        self.app = QApplication.instance() or QApplication([])
        view = GameView(lambda: ["GTA V"], title_ids=lambda: ["PPSA04263"])
        view.x11 = self.FakeX11()
        view.embed = lambda window, name: setattr(view, "embedded", window)
        return view

    def test_a_game_window_open_before_watching_is_taken(self):
        view = self.view()
        view.x11.windows = {0x1400002: ("AnyPS5 title runs", {"anyps5 title runs"}),
                            0x2000002: ("Grand Theft Auto V | FPS: 30", {"ppsa04263"})}
        view.watch()
        view.tick()
        self.assertEqual(view.embedded, 0x2000002)

    def test_the_next_run_with_the_same_window_id_is_taken(self):
        view = self.view()
        view.watch()
        view.x11.windows = {0x2000002: ("Grand Theft Auto V", {"ppsa04263"})}
        view.tick()
        del view.x11.windows[0x2000002]
        view.tick()  # the run ended
        self.assertIsNone(view.embedded)
        view.x11.windows = {0x2000002: ("Grand Theft Auto V", {"ppsa04263"})}
        view.tick()
        self.assertEqual(view.embedded, 0x2000002)

    def test_other_windows_are_left_alone(self):
        view = self.view()
        view.watch()
        view.x11.windows = {0x3000001: ("Grand Theft Auto V - YouTube", {"google-chrome"})}
        view.before = {0x3000001}
        view.tick()
        self.assertIsNone(view.embedded)
