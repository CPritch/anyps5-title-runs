"""The Games page and its commands: adding the games in a folder (with the tool's route where it has one), removing one,
and deleting a recorded scenario (a game set to it goes back to its default)."""

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

import helpers  # noqa: F401
from helpers import make_config

from title_runs import cli, configfile, engine as engines, pad, scenarios

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
try:
    from PySide6.QtWidgets import QApplication, QWidget
except ImportError:
    QApplication = None


def dump(folder, title_id, name, version="01.000.000"):
    """An extracted package as a game folder has it: eboot.bin and sce_sys/param.json."""
    folder = Path(folder) / f"{title_id}-app"
    (folder / "sce_sys").mkdir(parents=True)
    (folder / "eboot.bin").write_bytes(b"")
    (folder / "sce_sys" / "param.json").write_text(json.dumps({"titleId": title_id, "contentVersion": version,
                                                               "localizedParameters": {"defaultLanguage": "en-US", "en-US": {"titleName": name}}}))
    return folder


def recorded(config, scenario_id="house-walk"):
    folder = scenarios.recorded(config.state_dir, "PPSA04263")
    folder.mkdir(parents=True, exist_ok=True)
    base = scenarios.available("PPSA04263")["franklins-house"]
    data = {"title_id": "PPSA04263", "name": "House walk", "scene": "Franklin walks around his house", "route": "routes/PPSA04263.json",
            "frame": base["frame"], "input": {"from": "franklins-house", "recorded": {"at": "2026-10-24T09:56:01+00:00"},
                                              "track": [[0, *pad.NEUTRAL], [1000, 0, 128, 0, 128, 128], [150000, *pad.NEUTRAL]]}}
    (folder / f"{scenario_id}.json").write_text(json.dumps(data))


class Engine(unittest.TestCase):
    def setUp(self):
        self.config = make_config(titles={})
        configfile.save(self.config)
        self.engine = engines.Engine(self.config)
        self.games = Path(tempfile.mkdtemp())

    def test_adding_the_games_in_a_folder(self):
        dump(self.games, "PPSA04263", "Grand Theft Auto V")
        dump(self.games / "more", "PPSA01325", "Another Game")
        said = self.engine.add_games(self.games)
        self.assertTrue(said.startswith("Added ") and "Grand Theft Auto V (PPSA04263)" in said and "Another Game (PPSA01325)" in said, said)
        self.assertEqual(self.config.titles["PPSA04263"].route.name, "PPSA04263.json")  # this tool has GTA V's route
        self.assertIsNone(self.config.titles["PPSA01325"].route)  # a start-up check
        checks = {row["title_id"]: row["check"] for row in self.engine.titles()}
        self.assertEqual(checks, {"PPSA04263": "Full test", "PPSA01325": "Start-up check"})
        self.assertEqual(self.engine.add_games(self.games), "Every game in that folder is already set up.")
        self.assertIn("No games found there", self.engine.add_games(self.games / "more" / "PPSA01325-app" / "sce_sys"))

    def test_removing_a_game(self):
        dump(self.games, "PPSA04263", "Grand Theft Auto V")
        self.engine.add_games(self.games)
        self.engine.remove_game("PPSA04263")
        self.assertEqual(self.engine.titles(), [])
        self.assertTrue((self.games / "PPSA04263-app" / "eboot.bin").exists())  # its folder stays

    def test_deleting_a_recording(self):
        config = make_config()
        configfile.save(config)
        engine = engines.Engine(config)
        recorded(config)
        engine.set_scenarios("PPSA04263", ["prologue", "house-walk"])
        row = engine.titles()[0]
        walk = next(c for c in row["scenarios"] if c["id"] == "house-walk")
        self.assertEqual((walk["recorded"], walk["recorded_at"]), (True, "2026-10-24"))
        engine.delete_recording("PPSA04263", "house-walk")
        self.assertEqual(engine.config.titles["PPSA04263"].scenarios, ["prologue"])  # taken off the game's list
        self.assertNotIn("house-walk", [c["id"] for c in engine.titles()[0]["scenarios"]])
        with self.assertRaises(ValueError):
            engine.delete_recording("PPSA04263", "prologue")  # the tool's own


class CommandLine(unittest.TestCase):
    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_add_remove_and_delete_recording(self):
        config = make_config(titles={})
        configfile.save(config)
        games = Path(tempfile.mkdtemp())
        dump(games, "PPSA04263", "Grand Theft Auto V")
        code, out, _ = self.run_cli("--json", "--config", str(config.path), "games", "add", str(games))
        self.assertEqual((code, json.loads(out)), (0, {"added": ["PPSA04263"]}))
        self.assertEqual(self.run_cli("--config", str(config.path), "games", "add", str(games / "nothing"))[0], 1)
        recorded(config)
        code, out, _ = self.run_cli("--config", str(config.path), "games", "delete-recording", "PPSA04263", "house-walk")
        self.assertEqual((code, out.strip()), (0, "Deleted the recording house-walk."))
        self.assertEqual(self.run_cli("--config", str(config.path), "games", "remove", "PPSA04263")[0], 0)
        self.assertEqual(self.run_cli("--config", str(config.path), "games", "remove", "PPSA04263")[0], 1)


@unittest.skipIf(QApplication is None, "PySide6 is not installed")
class Page(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_the_page(self):
        from title_runs.ui.games import GamesPage
        config = make_config()
        configfile.save(config)
        engine = engines.Engine(config)
        recorded(config)
        page = GamesPage(engine)
        page.refresh()
        self.assertEqual(page.games.rowCount(), 1)
        self.assertEqual(page.games.item(0, 2).text(), "Full test")
        self.assertEqual((page.recorded.rowCount(), page.recorded.item(0, 0).text()), (1, "House walk (?)"))
        games = Path(tempfile.mkdtemp())
        dump(games, "PPSA01325", "Another Game")
        with mock.patch("title_runs.ui.dialogs.folder", return_value=str(games)):
            page.add()
        self.assertEqual(page.note.text(), "Added Another Game (PPSA01325).")
        self.assertEqual(page.games.rowCount(), 2)
        with mock.patch("title_runs.ui.dialogs.ask", return_value=True) as asked:
            page.recorded.cellWidget(0, 3).click()  # Delete
        self.assertEqual(asked.call_args.kwargs, {"danger": True})
        self.assertTrue(page.recorded.isHidden())
        self.assertFalse(page.none_recorded.isHidden())
        with mock.patch("title_runs.ui.dialogs.choose", return_value=["franklins-house", "prologue"]) as asked:
            page.choose(next(r for r in engine.titles() if r["title_id"] == "PPSA04263"))
        self.assertEqual(asked.call_args.args[3], ["prologue"])  # ticked to begin with: what the game is tested in now
        self.assertEqual(engine.config.titles["PPSA04263"].scenarios, ["franklins-house", "prologue"])
        self.assertIn("is tested in The prologue (a new game, no save), Franklin's front door (100% save).", page.note.text())


@unittest.skipIf(QApplication is None, "PySide6 is not installed")
class Dialogs(unittest.TestCase):
    """Sized from the window they come from: Qt's own open small on a tiling desktop."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_a_dialog_takes_a_share_of_its_window(self):
        from PySide6.QtWidgets import QDialog
        from title_runs.ui import dialogs
        window = QWidget()
        window.resize(1400, 1000)
        dialog = QDialog(window)
        dialogs.fit(dialog, window, 0.8, 0.75)
        self.assertEqual((dialog.width(), dialog.height()), (1120, 750))
        dialogs.fit(dialog, None, 0.1)  # no window: left as it is
        self.assertEqual(dialog.width(), 1120)


if __name__ == "__main__":
    unittest.main()
