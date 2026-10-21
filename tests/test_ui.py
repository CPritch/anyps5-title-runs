"""The window's model (no Qt), and the trust dialog's rules (offscreen Qt): Run anyway needs a scope, the box ticked and
the author's name typed exactly; Enter does not accept."""

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
