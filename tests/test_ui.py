"""The window's model (no Qt), and the window itself (offscreen Qt): the first-run walkthrough's gates, the testing
switch, Add on All pull requests, Home with local tests, the report window's traces and the game view."""

import os
import unittest
from pathlib import Path
from unittest import mock

import helpers  # noqa: F401
from helpers import make_config, make_pr

from title_runs.ui import model

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
try:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication
except ImportError:  # the window needs PySide6; the model does not
    QApplication = None

HEAD = "69ac2e155ad018ed1fb9028d2028d15999a8571e"


def listed(number, title="t", body="", labels=(), author="someuser", draft=False):
    return {"number": number, "title": title, "body": body, "draft": draft, "author": author, "head": HEAD, "labels": list(labels)}


class Model(unittest.TestCase):
    def test_four_sections(self):
        prs = [listed(8104, labels=["perf"]), listed(6488, body="- [x] Unblocks: PPSA04263"), listed(7000, labels=["agc"]), listed(7001),
               listed(7002, draft=True)]
        sections = model.pr_sections(prs, {8104}, {"PPSA04263": "GTA V"})
        self.assertEqual([[r["number"] for r in sections[name]] for name in model.SECTIONS], [[8104], [6488], [7000], [7001]])
        mine = sections[model.SECTIONS[0]][0]
        self.assertEqual((mine["badge"], mine["add"]), ("✓ on your list", False))
        mention = sections[model.SECTIONS[1]][0]
        self.assertEqual((mention["titles"], mention["badge"], mention["add"]), ("Unblocks PPSA04263", "", True))

    def test_search(self):
        sections = model.pr_sections([listed(1, "perf: fast"), listed(2, "fix: slow")], set(), {}, "fast")
        self.assertEqual(sum(len(v) for v in sections.values()), 1)

    def test_tray_states(self):
        self.assertEqual(model.tray_view({"state": "idle", "line": "Idle"}, [], [], "schedule")[0], "idle")
        self.assertEqual(model.tray_view({"state": "idle", "line": "Idle"}, [], [{"number": 1}], "schedule"), ("waiting", ["Idle", "1 PR waiting for you"]))
        self.assertEqual(model.tray_view({"state": "idle", "line": "Idle"}, [], [], "off")[1], ["Idle", "Testing is off: no test starts."])
        self.assertEqual(model.tray_view({"state": "error", "line": "Error: build failed"}, [], [], "schedule")[0], "error")
        state, lines = model.tray_view({"state": "running", "line": "Testing #8104 (a local test)"}, [{"number": 7922, "title": "perf: x"}], [], "schedule")
        self.assertEqual((state, lines), ("running", ["Testing #8104 (a local test)", "Next: #7922 perf: x"]))


if __name__ == "__main__":
    unittest.main()


@unittest.skipIf(QApplication is None, "PySide6 is not installed")
class Window(unittest.TestCase):
    """The walkthrough's gates (the sandbox page needs its box ticked; without idle detection, hours; the games), Finish
    marking it done, the testing switch, and the listing of the local tests' project."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        import tempfile

        from title_runs import config as configs
        from title_runs.ui import app

        self.root = Path(tempfile.mkdtemp())
        dumps = self.root / "dumps" / "PPSA04263-app"
        (dumps / "sce_sys").mkdir(parents=True)
        (dumps / "eboot.bin").write_bytes(b"")
        (dumps / "sce_sys" / "param.json").write_text('{"titleId": "PPSA04263", "contentVersion": "01.010.002", '
                                                       '"localizedParameters": {"defaultLanguage": "en-US", "en-US": {"titleName": "Grand Theft Auto V"}}}')
        clone = self.root / "anyps5"
        (clone / ".git").mkdir(parents=True)
        (clone / "CMakeLists.txt").write_text("")
        self.dumps = self.root / "dumps"
        self.config_path = self.root / "tester.toml"
        app.new_config(self.config_path, self.root / "state")
        self.config_path.write_text(self.config_path.read_text() + f'\n[source]\nrepo_dir = "{clone}"\n')
        self.patch = mock.patch("title_runs.platform_info.idle_detection", return_value=(False, "Hyprland does not tell logind"))
        self.patch.start()
        self.engine = app.Engine(configs.load(self.config_path))
        self.engine.client.info = {"gpu": "NVIDIA GeForce RTX 5060 Laptop GPU", "driver": "NVIDIA 615.71.09", "os": "Linux 7.2.8"}

    def tearDown(self):
        self.patch.stop()

    def test_walkthrough_gates_and_finish(self):
        from title_runs.ui.walkthrough import Walkthrough
        wizard = Walkthrough(self.engine, str(self.dumps))
        wizard.show()
        self.assertEqual(Walkthrough.PAGES, ("what", "sandbox", "when", "dumps", "done"))
        self.assertFalse(wizard.sandbox.isComplete())
        wizard.sandbox.read.setChecked(True)
        self.assertTrue(wizard.sandbox.isComplete())
        self.assertFalse(wizard.when.idle.isEnabled())
        self.assertEqual((wizard.when.first.value(), wizard.when.last.value()), (1, 7))
        wizard.when.last.setValue(1)
        self.assertFalse(wizard.when.isComplete())
        wizard.when.last.setValue(7)
        self.assertTrue(wizard.dumps.isComplete())
        self.assertFalse(self.engine.client.onboarded())
        self.assertEqual(self.engine.readiness()[0], False)
        wizard.accept()
        self.assertTrue(self.engine.client.onboarded())
        self.assertEqual(self.engine.config.schedule["hours"], [1, 7])
        self.assertFalse(self.engine.config.schedule["idle_only"])
        self.assertEqual(list(self.engine.config.titles), ["PPSA04263"])
        self.assertEqual(self.engine.readiness(), (True, "", ""))  # nothing left to set up, and nothing to sign in to

    def test_the_testing_switch(self):
        from title_runs import config as configs
        engine = self.engine
        with mock.patch.object(engine.client, "ready", return_value=(True, "")), \
                mock.patch.object(engine.client, "allowed_now", return_value=(False, "outside the hours 01-07")), \
                mock.patch.object(engine, "run_local", return_value="tested #8104 (a local test)") as run:
            engine.config.testing = "schedule"
            self.assertEqual(engine.next_test(), "outside the hours 01-07")
            run.assert_not_called()
            engine.set_testing("now")  # whatever the hours
            self.assertEqual(engine.next_test(), "tested #8104 (a local test)")
            run.assert_called_once()
            run.return_value = None
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

    def test_find_games_however_the_folder_is_given(self):
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

    def test_the_listing_is_of_the_local_tests_project(self):
        from title_runs import listing
        self.engine.config.local_repository = "CPritch/AnyPS5"
        other = listing.Listing.of(self.engine.config.state_dir, "boykopovar/AnyPS5")
        other.data["prs"]["6321"] = {"number": 6321}
        other.save()
        self.assertEqual(self.engine.listing(), [])  # another repository's listing is not shown
        self.assertEqual(self.engine.listing_note(), "Pull requests of CPritch/AnyPS5: not listed yet, Refresh reads them")
        with mock.patch("title_runs.gh.GitHubRepo.pages", return_value=[make_pr(6321, "a" * 40)]) as pages:
            self.engine.refresh_listing()  # Refresh
        self.assertEqual(pages.call_args.args[0], "/repos/CPritch/AnyPS5/pulls")
        self.assertEqual([pr["number"] for pr in self.engine.listing()], [6321])
        self.assertIn("Pull requests of CPritch/AnyPS5, listed", self.engine.listing_note())


@unittest.skipIf(QApplication is None, "PySide6 is not installed")
class LocalTestsInTheWindow(unittest.TestCase):
    """Ready once the walkthrough is done; Home shows the heads waiting and the results; Add on All pull requests puts a
    pull request on the local tests list."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        import tempfile

        from title_runs import listing
        from title_runs.ui import app
        self.listing = Path(tempfile.mkdtemp()) / "listing.json"
        store = listing.Listing(self.listing)
        store.data["repository"] = "boykopovar/AnyPS5"
        store.data["prs"] = {str(pr["number"]): listing.shape(pr) for pr in (make_pr(6488, "a" * 40, body="- [x] Unblocks: PPSA04263"),
                                                                           make_pr(4287, "7" * 40))}
        store.save()
        self.config = make_config(local_repository="boykopovar/AnyPS5", local_prs=[4287])
        self.engine = app.Engine(self.config, listing=self.listing)
        self.engine.client.finish_onboarding({"idle": "hours"})

    def test_ready_after_the_walkthrough(self):
        self.assertEqual(self.engine.client.ready(), (True, ""))
        self.assertEqual(self.engine.readiness(), (True, "", ""))

    def test_home_shows_whats_waiting(self):
        from title_runs.ui.home import HomePage
        self.engine.local.write({"repository": "boykopovar/AnyPS5", "entries": [{"pr": 4287, "head": "7" * 40, "title": "perf(shader): pick", "author": "karanvora2599",
                                                                              "added": "2026-10-23T12:00:00Z", "status": "queued"}]})
        self.assertEqual(self.engine.up_next_rows()[0]["why"], "Waiting to be tested")
        with mock.patch.object(self.engine.client, "allowed_now", return_value=(True, "")):
            self.assertEqual(self.engine.home()["headline"], "Starting the next test")
            self.engine.config.testing = "off"
            self.assertEqual(self.engine.home()["kind"], "off")
            home = HomePage(self.engine)
            home.refresh()
        self.assertIn("#4287", home.upcoming.rows[0])
        self.assertIn("No results yet", home.recent.rows[0])

    def test_add_on_all_pull_requests(self):
        from title_runs.ui.window import PullRequestsTab
        tab = PullRequestsTab(self.engine)
        tab.refresh()
        mine, mentions = tab.tree.topLevelItem(0), tab.tree.topLevelItem(1)
        self.assertEqual((mine.text(0), mentions.text(0)), ("On your local tests (1)", "Mentions your titles (1)"))
        self.assertIsNone(tab.tree.itemWidget(mine.child(0), 4))  # on the list already: no Add
        add = tab.tree.itemWidget(mentions.child(0), 4)
        self.assertEqual(add.text(), "Add")
        add.click()
        self.assertEqual(self.engine.config.local_prs, [4287, 6488])
        self.assertTrue(tab.added.text().startswith("Added #6488."))
        self.assertEqual(tab.tree.topLevelItem(0).text(0), "On your local tests (2)")


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

    def test_header_states(self):
        best = {"number": 1}
        running = {"state": "running", "job": {"pr": 1, "title": "perf: x"}, "progress": "PR run 1, 2/4"}
        self.assertEqual(model.header(running, True, "", "schedule", True, "", best)["detail"], "Run 2 of 4: with the change")
        self.assertEqual(model.header(running, True, "", "off", True, "", best)["kind"], "running")  # Off starts nothing; Stop ends a test
        self.assertEqual(model.header({}, False, "no titles are set up", "schedule", True, "", best)["detail"], "Add a game you own.")
        self.assertEqual(model.header({}, True, "", "schedule", True, "", None)["kind"], "idle")
        self.assertEqual(model.header({}, True, "", "off", True, "", best)["kind"], "off")
        waiting = model.header({}, True, "", "schedule", False, "outside the hours 01-07", best)
        self.assertEqual(waiting["detail"], "The next test starts by itself between 01:00 and 07:00, the hours you chose.")
        self.assertEqual(model.header({}, True, "", "now", False, "outside the hours 01-07", best)["kind"], "ready")  # Now: whatever the hours
        self.assertEqual(model.waiting_for("on battery"), "the computer is plugged in")
        self.assertEqual(model.waiting_for("gtav.elf is running"), "gtav.elf has closed")


@unittest.skipIf(QApplication is None, "PySide6 not installed")
class ReportWindowTraces(unittest.TestCase):
    """The report window lists the result's traces to drag into the comment, all selected; one over GitHub's limit is
    listed, can't be dragged, and the window says the report lacks what the form asks for."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def dialog(self, files):
        import tempfile
        import types
        from title_runs.ui.local import ReportDialog
        folder = Path(tempfile.mkdtemp())
        for item in files:
            if item["fits"]:
                item["file"] = folder / item["name"]
                item["file"].write_bytes(b"")
        entry = {"pr": 4287, "head": "7" * 40, "main": "4" * 40, "at": "2026-10-23T12:00:00Z", "job": "4287-777777777777-prologue"}
        engine = types.SimpleNamespace(local_results=lambda number: [{"entry": entry, "text": "Ran this on ...", "stale": "", "link": "https://example.org/pull/4287"}],
                                       local_attachments=lambda entry: (folder, files))
        return ReportDialog(engine, 4287)

    def test_the_traces_are_selected_to_drag_together(self):
        files = [{"name": f"aps5-trace-c49fa17ee046-3-PPSA04263-main-{n}.json.gz", "size": 19_400_000, "fits": True} for n in (1, 2)]
        dialog = self.dialog(files)
        self.assertEqual(dialog.files.count(), 2)
        self.assertEqual(dialog.files.item(0).text(), "aps5-trace-c49fa17ee046-3-PPSA04263-main-1.json.gz   19.4 MB")
        urls = dialog.files.mimeData(dialog.files.selectedItems()).urls()
        self.assertEqual([url.toLocalFile() for url in urls], [str(f["file"]) for f in files])
        self.assertTrue(dialog.too_big.isHidden())

    def test_a_trace_over_githubs_limit_is_listed_and_not_dragged(self):
        files = [{"name": "aps5-trace-c49fa17ee046-3-PPSA04263-main-1.json.gz", "size": 19_400_000, "fits": True},
                 {"name": "aps5-trace-c49fa17ee046-3-PPSA04263-main-2.json.gz", "size": 35_600_000, "fits": False}]
        dialog = self.dialog(files)
        big = dialog.files.item(1)
        self.assertEqual(big.text(), "aps5-trace-c49fa17ee046-3-PPSA04263-main-2.json.gz   35.6 MB, over GitHub's 25 MB")
        self.assertFalse(big.flags() & Qt.ItemIsDragEnabled)
        self.assertEqual(len(dialog.files.selectedItems()), 1)
        self.assertIn("1 of these traces can't be attached", dialog.too_big.text())
        self.assertFalse(dialog.too_big.isHidden())

    def test_no_traces_no_list(self):
        self.assertTrue(self.dialog([]).files_box.isHidden())


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
