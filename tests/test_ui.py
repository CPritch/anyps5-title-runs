"""The window's model (no Qt), and the trust dialog's rules (offscreen Qt): Run anyway needs a scope, the box ticked and
the author's name typed exactly; Enter does not accept."""

import json
import os
import unittest

import helpers  # noqa: F401

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
        self.assertEqual(model.tray_view({"state": "idle", "line": "Idle"}, view, [], None)[0], "idle")
        self.assertEqual(model.tray_view({"state": "idle", "line": "Idle"}, view, [{"number": 1}], None), ("waiting", ["Idle", "1 PR waiting for you"]))
        self.assertEqual(model.tray_view({"state": "error", "line": "Error: build failed"}, view, [], None)[0], "error")
        running = {"running": {"number": 8104}, "up_next": [{"number": 7922, "score": 4, "titles": "GTA V", "priority": "high"}], "recent": []}
        state, lines = model.tray_view({"state": "running", "line": "Running: #8104 · PPSA04263 · main run 2/4"}, running, [], None)
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
        window = MainWindow(self.engine)
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
        window.settings.url.setText(str(other.results_git))
        window.settings.save()
        self.assertEqual(self.engine.client.results_repository(), "maintainer2/results")
        self.assertIn("Now using maintainer2/results.", window.settings.check_label.text())
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
        window = MainWindow(self.engine)
        window.refresh()
        self.assertIn("1 from accounts without a registered machine", window.overview.ignored.text())
        self.assertIn("The workflow did not use your comment", window.queue.not_ready.text())

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
            self.assertIn("did not use your comment", self.engine.ignored_mine())
        with mock.patch.object(self.engine.client.repo, "cursors", return_value=stale), \
                mock.patch("title_runs.formats.now", return_value=formats.parse_time("2026-10-23T20:00:00Z")):
            self.assertEqual(self.engine.ignored_mine(), "")  # more than a day old
