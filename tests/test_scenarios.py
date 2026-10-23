"""Scenarios (scenarios.py): the scenario file, the save's download and checks, where it goes, the scene check, and
what scenarios change elsewhere (runs folders, combined verdicts, the result format, the report, the config file)."""

import hashlib
import io
import json
import struct
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

import helpers  # noqa: F401  (puts the repository on sys.path)
from title_runs import config as configs, configfile, local_tests, protocol, route as routes, scenarios, verdict

SAVE = b"\x00\x00\x00\x01(\x00A\x00u\x00t\x00o\x00s\x00a\x00v\x00e\x00)" + bytes(1000)


def zipped(name, data):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        archive.writestr(name, data)
    return out.getvalue()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def bmp(path, colour, width=192, height=108):
    """A 32-bit top-down BMP of one colour (what APS5_DUMP_FRAMES writes, in miniature)."""
    pixels = bytes([colour[2], colour[1], colour[0], 255]) * (width * height)
    header = b"BM" + struct.pack("<IHHI", 54 + len(pixels), 0, 0, 54) + struct.pack("<IiiHHIIiiII", 40, width, -height, 1, 32, 0, len(pixels), 0, 0, 0, 0)
    Path(path).write_bytes(header + pixels)
    return Path(path)


class Opener:
    def __init__(self, data):
        self.data, self.calls = data, 0

    def __call__(self, url, timeout=None):
        self.calls += 1
        return io.BytesIO(self.data)


def scenario_file(directory, name="house", **changes):
    archive = zipped("savedata0/memory.dat", SAVE)
    data = {"title_id": "PPSA04263", "name": "A house", "scene": "a house, after Resume Story with a 100% save",
            "route": "routes/PPSA04263.json",
            "save": {"about": "a 100% save", "page": "https://example.org/saves", "url": "https://example.org/saves/1.zip",
                     "sha256": sha(archive), "file": "savedata0/memory.dat", "file_sha256": sha(SAVE), "into": {"memory_slot": 0}},
            "still": {"press": "left", "every": 10, "why": "it keeps the idle camera from turning"}}
    data.update(changes)
    path = Path(directory) / f"{name}.json"
    path.write_text(json.dumps(data))
    return path, archive


class ScenarioFile(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

    def test_a_good_file_loads_with_its_id_and_route(self):
        path, _ = scenario_file(self.dir)
        scenario = scenarios.load(path)
        self.assertEqual(scenario["id"], "house")
        self.assertEqual(scenario["route"], scenarios.ROOT / "routes" / "PPSA04263.json")

    def test_what_a_scenario_file_may_not_be(self):
        save = {"url": "https://example.org/1.zip", "sha256": "0" * 64}
        cases = {"Bad_Name": {}, "long": {"scene": "x" * 121}, "plain": {"save": dict(save, url="http://example.org/1.zip", into={"memory_slot": 0})},
                 "nosha": {"save": dict(save, sha256="abc", into={"memory_slot": 0})},
                 "dir": {"save": dict(save, into={"directory": "SAVEDATASGTA50000"})},
                 "frame": {"frame": {"colours": [0.5, 0.5], "max_distance": 0.25}},
                 "still": {"still": {"press": "jump", "every": 10}}, "often": {"still": {"press": "left", "every": 40}}}
        for name, change in cases.items():
            path, _ = scenario_file(self.dir, name, **change)
            with self.subTest(name), self.assertRaises(scenarios.ScenarioError):
                scenarios.load(path)

    def test_a_title_names_its_scenario_by_id_or_path_and_else_has_its_default(self):
        path, _ = scenario_file(self.dir)
        self.assertEqual(scenarios.of(configs.Title("PPSA04263", Path("/dump"), scenario=str(path)))["id"], "house")
        self.assertEqual(scenarios.of(configs.Title("PPSA04263", Path("/dump")))["id"], "prologue")
        self.assertIsNone(scenarios.of(configs.Title("PPSA01325", Path("/dump"))))  # no scenarios: the route alone, as before
        with self.assertRaises(scenarios.ScenarioError):
            scenarios.of(configs.Title("PPSA04263", Path("/dump"), scenario="no-such-scenario"))
        other, _ = scenario_file(self.dir, "other", title_id="PPSA01325")
        with self.assertRaises(scenarios.ScenarioError):
            scenarios.of(configs.Title("PPSA04263", Path("/dump"), scenario=str(other)))

    def test_the_tools_own_scenarios_load_with_the_default_first(self):
        found = scenarios.available("PPSA04263")
        self.assertEqual(list(found)[0], "prologue")
        for key, scenario in found.items():
            with self.subTest(key):
                self.assertTrue(scenario["route"].exists())
                self.assertTrue(scenario.get("frame"), "a scenario of the tool's own has the scene's colours")
        self.assertTrue(found["franklins-house"]["save"])
        self.assertFalse(found["prologue"].get("save"))


class Save(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        path, self.archive = scenario_file(self.dir)
        self.scenario = scenarios.load(path)

    def test_downloaded_once_checked_and_kept(self):
        opener = Opener(self.archive)
        first = scenarios.fetch(self.scenario["save"], self.dir / "saves", opener)
        self.assertEqual(first.read_bytes(), SAVE)
        self.assertEqual(scenarios.fetch(self.scenario["save"], self.dir / "saves", opener), first)
        self.assertEqual(opener.calls, 1)

    def test_a_download_that_isnt_the_named_one_is_refused(self):
        with self.assertRaisesRegex(scenarios.ScenarioError, "is not the one the scenario names"):
            scenarios.fetch(self.scenario["save"], self.dir / "saves", Opener(zipped("savedata0/memory.dat", b"something else")))
        changed = dict(self.scenario["save"], file_sha256=sha(b"other"))
        with self.assertRaisesRegex(scenarios.ScenarioError, "memory.dat is not the one"):
            scenarios.fetch(changed, self.dir / "saves", Opener(self.archive))
        missing = dict(self.scenario["save"], file="savedata0/../../etc/passwd")
        with self.assertRaisesRegex(scenarios.ScenarioError, "no savedata0"):
            scenarios.fetch(missing, self.dir / "saves", Opener(self.archive))

    def test_it_goes_where_anyps5_keeps_save_data_memory(self):
        [(source, relative)] = scenarios.files(self.scenario, self.dir / "saves", Opener(self.archive))
        self.assertEqual(relative, Path("_sd_mem/u268435456/slot0.bin"))
        self.assertEqual(source.read_bytes(), SAVE)
        self.assertEqual(scenarios.files(None, self.dir / "saves"), [])

    def test_the_reports_words_let_others_load_the_same_save(self):
        words = scenarios.save_words(self.scenario)
        self.assertIn("a 100% save (https://example.org/saves, its memory.dat, sha256 " + sha(SAVE)[:12], words)
        self.assertIn("save-data memory slot 0 (_sd_mem/u268435456/slot0.bin)", words)
        self.assertEqual(scenarios.input_words(self.scenario), "with D-pad left pressed every 10 s (it keeps the idle camera from turning) and no other input")
        self.assertEqual(scenarios.input_words(None), "with no input")


class Check(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.house = bmp(self.dir / "frame_001.bmp", (120, 90, 60))
        self.scenario = {"id": "house", "name": "A house", "frame": {"colours": scenarios.colours(self.house), "max_distance": 0.25}}

    def test_the_scene_is_its_colours(self):
        self.assertEqual(scenarios.check(self.scenario, self.house)[0], True)
        found, words = scenarios.check(self.scenario, bmp(self.dir / "frame_002.bmp", (230, 230, 240)))
        self.assertIs(found, False)
        self.assertIn("frame_002.bmp is 1.00 from the scene's colours (at most 0.25)", words)

    def test_a_black_frame_is_never_in_the_scene(self):
        dark = bmp(self.dir / "frame_003.bmp", (0, 0, 0))
        scenario = dict(self.scenario, frame={"colours": scenarios.colours(dark), "max_distance": 0.25})
        self.assertEqual(scenarios.check(scenario, dark), (False, "frame_003.bmp is black"))

    def test_unknown_without_reference_colours_or_a_frame(self):
        self.assertIsNone(scenarios.check({"id": "x"}, self.house)[0])
        self.assertIsNone(scenarios.check(self.scenario, None)[0])
        self.assertIsNone(scenarios.check(self.scenario, self.dir / "missing.bmp")[0])

    def test_a_run_that_isnt_in_the_scene_fails_its_route(self):
        run = self.dir / "run"
        run.mkdir()
        (run / "meta").write_text("")
        (run / "actions").write_text("")
        measure = protocol.Protocol(helpers.make_config(), None, {"steps": []}, self.dir / "runs", [], lambda text: None, scenario=self.scenario)
        measure.in_scene(None, run, self.house)
        with self.assertRaisesRegex(routes.RouteFailed, "not the scene of A house"):
            measure.in_scene(None, run, bmp(self.dir / "frame_004.bmp", (230, 230, 240)))
        self.assertIn("scenario=house scene_check=no", (run / "meta").read_text())


class Elsewhere(unittest.TestCase):
    def test_a_scenarios_runs_are_its_own(self):
        self.assertEqual(scenarios.runs_name("PPSA04263", None), "PPSA04263")
        self.assertEqual(scenarios.runs_name("PPSA04263", {"id": "house"}), "PPSA04263-house")

    def test_machines_are_combined_only_within_a_scenario(self):
        info = {"gpu": "NVIDIA GeForce RTX 5060 Laptop GPU", "os": "Linux 7.2.8", "driver": "NVIDIA 615.71.09"}
        sides = {"A": {"p50": [79.1, 79.0]}, "B": {"p50": [73.8, 74.0]}}
        results = {"one": {"status": "done", "class": info, "titles": {"PPSA04263": {"sides": sides, "scenario": "prologue"}}},
                   "two": {"status": "done", "class": info, "titles": {"PPSA04263": {"sides": sides, "scenario": "house"}}}}
        keys = sorted(verdict.by_class(results, "PPSA04263"))
        self.assertEqual([key.rsplit(" in ", 1)[1] for key in keys], ["house", "prologue"])
        self.assertEqual({c["n"] for c in verdict.by_class(results, "PPSA04263").values()}, {1})

    def test_the_config_file_keeps_the_scenario(self):
        config = helpers.make_config()
        config.titles["PPSA04263"].scenario = "franklins-house"
        configfile.save(config)
        self.assertEqual(configs.load(config.path).titles["PPSA04263"].scenario, "franklins-house")

    def test_the_report_names_the_save_and_the_input(self):
        results = {"pr": 4287, "head": "7" * 40, "base": "c" * 40,
                   "titles": {"PPSA04263": {"scene": "a house", "input": "with D-pad left pressed every 10 s and no other input",
                                            "save": "The save is a 100% save (https://example.org/saves).",
                                            "ab": {"warm": {"A": {"warm": "already"}, "B": {"warm": "already"}},
                                                   "runs": [{"run": f"{s}{n}", "side": s, "counts": True, "capture": "counts; no pipeline builds",
                                                             "summary": {"frame_ms": {"p50": 80.0}, "title": "Grand Theft Auto V"}}
                                                            for n in (1, 2) for s in "AB"]}}}}
        text = local_tests.report_text(results, {"pr": 4287, "head": "7" * 40, "main": "4" * 40})
        self.assertIn(", a house, with D-pad left pressed every 10 s and no other input.", text.splitlines()[0])
        self.assertIn("The save is a 100% save (https://example.org/saves).", text.splitlines()[1])


if __name__ == "__main__":
    unittest.main()
