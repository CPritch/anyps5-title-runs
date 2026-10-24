"""Recording a scenario (recording.py, Engine.record_scenario, `title-runs games record`, the window's Record dialog):
what is checked before the game starts, the new scenario's file, the status while it records, and nothing saved when
it is stopped. The session itself (the game, the controller) is replaced here; the real one needs a controller."""

import io
import json
import os
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

import helpers  # noqa: F401
from helpers import make_config

from title_runs import cli, configfile, engine as engines, pad, recording, scenarios

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
try:
    from PySide6.QtWidgets import QApplication
except ImportError:
    QApplication = None

TRACK = [[0, *pad.NEUTRAL], [1000, 0, 128, 0, 128, 128], [150000, *pad.NEUTRAL]]


class Controller:
    name = "Test pad"
    closed = False

    def close(self):
        self.closed = True


class Check(unittest.TestCase):
    def setUp(self):
        self.config = make_config()

    def test_what_stops_a_recording_before_the_game_starts(self):
        ok = ("PPSA04263", "franklins-house", "out-of-the-house", "Out of the house", "Franklin walks to the road", 150)
        self.assertEqual(recording.check(self.config, *ok)["id"], "franklins-house")
        for changed, words in (((0, "PPSA01325"), "not one of your games"), ((1, "the-moon"), "no scenario 'the-moon'"),
                               ((2, "Out of the house"), "not a scenario id"), ((2, "prologue"), "has a scenario 'prologue' already"),
                               ((3, " "), "needs a name"), ((4, "x" * 121), "up to 120 characters"),
                               ((5, 60), "100 to 600 seconds")):
            asked = list(ok)
            asked[changed[0]] = changed[1]
            with self.subTest(changed=changed), self.assertRaisesRegex(recording.RecordError, words):
                recording.check(self.config, *asked)

    def test_an_id_from_the_name(self):
        self.assertEqual(recording.new_id("Out of the house!"), "out-of-the-house")
        self.assertEqual(recording.new_id("Out of the house", {"out-of-the-house", "out-of-the-house-2"}), "out-of-the-house-3")
        self.assertEqual(recording.new_id("???"), "recorded")

    def test_main_must_be_built(self):
        base = scenarios.available("PPSA04263")["franklins-house"]
        with self.assertRaisesRegex(recording.RecordError, "main isn't built on this computer yet"):
            recording.main_side(self.config, self.config.titles["PPSA04263"], base)


class Saved(unittest.TestCase):
    def test_the_new_scenario_is_the_start_with_the_play(self):
        config = make_config()
        base = scenarios.available("PPSA04263")["franklins-house"]
        path = recording.save(config, "PPSA04263", base, "out-of-the-house", "Out of the house", "Franklin walks to the road", TRACK,
                              "1" * 40, "Test pad")
        self.assertEqual(path, config.state_dir / "scenarios" / "PPSA04263" / "out-of-the-house.json")
        saved = json.loads(path.read_text())
        self.assertEqual(saved["route"], "routes/PPSA04263.json")
        self.assertEqual((saved["save"], saved["start"], saved["still"], saved["frame"]), (base["save"], base["start"], base["still"], base["frame"]))
        self.assertEqual(saved["input"]["from"], "franklins-house")
        self.assertEqual(saved["input"]["recorded"]["main"], "1" * 40)
        found = scenarios.available("PPSA04263", config.state_dir)
        self.assertEqual(found["out-of-the-house"]["input"]["track"], TRACK)
        self.assertFalse(found["out-of-the-house"].get("default"))


class InTheEngine(unittest.TestCase):
    def setUp(self):
        self.config = make_config()
        configfile.save(self.config)
        self.engine = engines.Engine(self.config)

    def test_the_status_says_what_it_does_and_the_scenario_is_saved(self):
        seen = []

        def session(config, title, base, seconds, controller, log, progress, should_stop):
            progress("play now: 12 of 150 s")
            seen.append(dict(self.engine.status()))
            return TRACK, "1" * 40
        controller = Controller()
        with mock.patch("title_runs.recording.session", side_effect=session):
            path = self.engine.record_scenario("PPSA04263", "franklins-house", "walk", "A walk", "Franklin walks", 150, controller=controller)
        self.assertEqual((seen[0]["state"], seen[0]["job"], seen[0]["line"]),
                         ("running", {"recording": "walk", "title": "A walk"}, "Recording A walk: play now: 12 of 150 s"))
        self.assertTrue(path.exists() and controller.closed)
        self.assertEqual(self.engine.status()["state"], "idle")
        self.assertIn("Recorded A walk", self.engine.status()["line"])

    def test_stopped_nothing_saved(self):
        def session(config, title, base, seconds, controller, log, progress, should_stop):
            self.engine.client.status.update(stop_requested=True)  # Stop on Home, or title-runs stop
            raise recording.RecordError(f"{should_stop()}: nothing was saved")
        with mock.patch("title_runs.recording.session", side_effect=session), self.assertRaises(recording.RecordError):
            self.engine.record_scenario("PPSA04263", "franklins-house", "walk", "A walk", "Franklin walks", 150, controller=Controller())
        self.assertEqual(self.engine.status()["line"], "Not recorded: stopped: nothing was saved")
        self.assertFalse((self.config.state_dir / "scenarios" / "PPSA04263" / "walk.json").exists())

    def test_without_a_controller(self):
        with mock.patch("title_runs.pad.controllers", return_value=[]), self.assertRaisesRegex(pad.PadError, "no game controller"):
            self.engine.record_scenario("PPSA04263", "franklins-house", "walk", "A walk", "Franklin walks", 150)
        self.assertEqual(self.engine.status()["line"], "Not recorded: no game controller is connected")


class OnTheCommandLine(unittest.TestCase):
    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_games_record(self):
        config = make_config()
        configfile.save(config)

        def recorded(title_id, from_id, scenario_id, name, scene, seconds, say=None):
            say("getting to the scene")
            return config.state_dir / "scenarios" / title_id / f"{scenario_id}.json"
        with mock.patch("title_runs.engine.Engine.record_scenario", side_effect=recorded) as record:
            code, out, _ = self.run_cli("--json", "--config", str(config.path), "games", "record", "PPSA04263", "--from", "franklins-house",
                                        "--name", "Out of the house", "--scene", "Franklin walks to the road")
        self.assertEqual(code, 0)
        lines = [json.loads(line) for line in out.splitlines()]
        self.assertEqual(lines[0], {"progress": "getting to the scene"})
        self.assertEqual(lines[-1]["recorded"], "out-of-the-house")
        self.assertEqual(record.call_args.args, ("PPSA04263", "franklins-house", "out-of-the-house", "Out of the house", "Franklin walks to the road", 150))
        with mock.patch("title_runs.engine.Engine.record_scenario", side_effect=recording.RecordError("the scene never showed after Resume Story")):
            code, _, err = self.run_cli("--config", str(config.path), "games", "record", "PPSA04263", "--from", "franklins-house",
                                        "--name", "Out", "--scene", "Out")
        self.assertEqual((code, err.strip()), (1, "title-runs: Not recorded: the scene never showed after Resume Story"))


@unittest.skipIf(QApplication is None, "PySide6 is not installed")
class TheDialog(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def dialog(self, controller):
        from title_runs.ui.record import RecordDialog
        config = make_config()
        engine = engines.Engine(config)
        with mock.patch.object(engine, "controller", return_value=controller), \
                mock.patch("title_runs.engine.platform_info.find_dumps", return_value=[]):
            return engine, RecordDialog(engine)

    def test_record_hands_it_to_the_worker(self):
        engine, dialog = self.dialog({"name": "DualSense Wireless Controller", "path": "/dev/input/event20"})
        self.assertEqual(dialog.controller.text(), "DualSense Wireless Controller")
        starts = [dialog.start.itemData(i) for i in range(dialog.start.count())]
        self.assertEqual(sorted(starts), ["franklins-house", "prologue"])
        dialog.start.setCurrentIndex(starts.index("franklins-house"))
        dialog.record.click()
        self.assertIn("needs a name", dialog.note.text())  # nothing asked of the worker yet
        self.assertTrue(engine.work.empty())
        dialog.name.setText("Out of the house")
        dialog.scene.setText("Franklin walks out of his house to the road")
        dialog.record.click()
        self.assertEqual(engine.work.get_nowait(), ("record", {"title_id": "PPSA04263", "from_id": "franklins-house", "scenario_id": "out-of-the-house",
                                                                "name": "Out of the house", "scene": "Franklin walks out of his house to the road",
                                                                "seconds": 150}))

    def test_no_controller_no_record(self):
        _, dialog = self.dialog(None)
        self.assertFalse(dialog.record.isEnabled())
        self.assertIn("No controller found", dialog.controller.text())

    def test_home_while_recording(self):
        from title_runs.ui import model
        header = model.header({"state": "running", "job": {"recording": "walk", "title": "A walk"}, "progress": "play now: 12 of 150 s"},
                              True, "", "off", True, "", None)
        self.assertEqual((header["headline"], header["detail"], header["step"]), ("Recording a scenario: A walk", "play now: 12 of 150 s", -1))


if __name__ == "__main__":
    unittest.main()
