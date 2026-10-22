"""Scenes from saves (scenes.py): the scene file, the save's download and checks, where it goes, the scene check, and
what scenes change elsewhere (runs folders, combined verdicts, the result format, the report, the config file)."""

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
from title_runs import config as configs, configfile, formats, local_tests, protocol, route as routes, scenes, verdict

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
    b, g, r = colour[2], colour[1], colour[0]
    pixels = bytes([b, g, r, 255]) * (width * height)
    header = b"BM" + struct.pack("<IHHI", 54 + len(pixels), 0, 0, 54) + struct.pack("<IiiHHIIiiII", 40, width, -height, 1, 32, 0, len(pixels), 0, 0, 0, 0)
    Path(path).write_bytes(header + pixels)
    return Path(path)


class Opener:
    def __init__(self, data):
        self.data, self.calls = data, 0

    def __call__(self, url, timeout=None):
        self.calls += 1
        return io.BytesIO(self.data)


def scene_file(directory, name="house", **changes):
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


class SceneFile(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

    def test_a_good_file_loads_with_its_id_and_route(self):
        path, _ = scene_file(self.dir)
        scene = scenes.load(path)
        self.assertEqual(scene["id"], "house")
        self.assertEqual(scene["route"], scenes.ROOT / "routes" / "PPSA04263.json")

    def test_what_a_scene_file_may_not_be(self):
        cases = {"Bad_Name": {}, "long": {"scene": "x" * 121}, "plain": {"save": {"url": "http://example.org/1.zip", "sha256": "0" * 64,
                                                                                    "into": {"memory_slot": 0}}},
                 "nosha": {"save": {"url": "https://example.org/1.zip", "sha256": "abc", "into": {"memory_slot": 0}}},
                 "dir": {"save": {"url": "https://example.org/1.zip", "sha256": "0" * 64, "into": {"directory": "SAVEDATASGTA50000"}}},
                 "frame": {"frame": {"colours": [0.5, 0.5], "max_distance": 0.25}},
                 "still": {"still": {"press": "jump", "every": 10}}, "often": {"still": {"press": "left", "every": 40}}}
        for name, change in cases.items():
            path, _ = scene_file(self.dir, name, **change)
            with self.subTest(name), self.assertRaises(scenes.SceneError):
                scenes.load(path)

    def test_a_title_names_its_scene_by_id_or_path(self):
        path, _ = scene_file(self.dir)
        title = configs.Title("PPSA04263", Path("/dump"), scene=str(path))
        self.assertEqual(scenes.of(title)["id"], "house")
        self.assertIsNone(scenes.of(configs.Title("PPSA04263", Path("/dump"))))
        with self.assertRaises(scenes.SceneError):
            scenes.of(configs.Title("PPSA04263", Path("/dump"), scene="no-such-scene"))
        other, _ = scene_file(self.dir, "other", title_id="PPSA01325")
        with self.assertRaises(scenes.SceneError):
            scenes.of(configs.Title("PPSA04263", Path("/dump"), scene=str(other)))


class Save(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        path, self.archive = scene_file(self.dir)
        self.scene = scenes.load(path)

    def test_downloaded_once_checked_and_kept(self):
        opener = Opener(self.archive)
        first = scenes.fetch(self.scene["save"], self.dir / "saves", opener)
        self.assertEqual(first.read_bytes(), SAVE)
        self.assertEqual(scenes.fetch(self.scene["save"], self.dir / "saves", opener), first)
        self.assertEqual(opener.calls, 1)

    def test_a_download_that_isnt_the_named_one_is_refused(self):
        with self.assertRaisesRegex(scenes.SceneError, "is not the one the scene names"):
            scenes.fetch(self.scene["save"], self.dir / "saves", Opener(zipped("savedata0/memory.dat", b"something else")))
        changed = dict(self.scene["save"], file_sha256=sha(b"other"))
        with self.assertRaisesRegex(scenes.SceneError, "memory.dat is not the one"):
            scenes.fetch(changed, self.dir / "saves", Opener(self.archive))
        missing = dict(self.scene["save"], file="savedata0/../../etc/passwd")
        with self.assertRaisesRegex(scenes.SceneError, "no savedata0"):
            scenes.fetch(missing, self.dir / "saves", Opener(self.archive))

    def test_it_goes_where_anyps5_keeps_save_data_memory(self):
        [(source, relative)] = scenes.files(self.scene, self.dir / "saves", Opener(self.archive))
        self.assertEqual(relative, Path("_sd_mem/u268435456/slot0.bin"))
        self.assertEqual(source.read_bytes(), SAVE)
        self.assertEqual(scenes.files(None, self.dir / "saves"), [])

    def test_the_reports_words_let_others_load_the_same_save(self):
        words = scenes.save_words(self.scene)
        self.assertIn("a 100% save (https://example.org/saves, its memory.dat, sha256 " + sha(SAVE)[:12], words)
        self.assertIn("save-data memory slot 0 (_sd_mem/u268435456/slot0.bin)", words)
        self.assertEqual(scenes.input_words(self.scene), "with D-pad left pressed every 10 s (it keeps the idle camera from turning) and no other input")
        self.assertEqual(scenes.input_words(None), "with no input")


class Check(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.house = bmp(self.dir / "frame_001.bmp", (120, 90, 60))
        self.scene = {"id": "house", "frame": {"colours": scenes.colours(self.house), "max_distance": 0.25}}

    def test_the_scene_is_its_colours(self):
        self.assertEqual(scenes.check(self.scene, self.house)[0], True)
        found, words = scenes.check(self.scene, bmp(self.dir / "frame_002.bmp", (230, 230, 240)))
        self.assertIs(found, False)
        self.assertIn("frame_002.bmp is 1.00 from the scene's colours (at most 0.25)", words)

    def test_unknown_without_a_reference_or_a_frame(self):
        self.assertIsNone(scenes.check({"id": "x"}, self.house)[0])
        self.assertIsNone(scenes.check(self.scene, None)[0])
        self.assertIsNone(scenes.check(self.scene, self.dir / "missing.bmp")[0])

    def test_a_run_that_isnt_in_the_scene_fails_its_route(self):
        run = self.dir / "run"
        run.mkdir()
        (run / "meta").write_text("")
        (run / "actions").write_text("")
        measure = protocol.Protocol(helpers.make_config(), None, {"steps": []}, self.dir / "runs", [], lambda text: None, scene=self.scene)
        measure.in_scene(None, run, self.house)
        with self.assertRaisesRegex(routes.RouteFailed, "the save may not have loaded"):
            measure.in_scene(None, run, bmp(self.dir / "frame_003.bmp", (230, 230, 240)))
        self.assertIn("scene=house scene_check=no", (run / "meta").read_text())


class Elsewhere(unittest.TestCase):
    def test_a_scenes_runs_are_its_own(self):
        self.assertEqual(scenes.runs_name("PPSA04263", None), "PPSA04263")
        self.assertEqual(scenes.runs_name("PPSA04263", {"id": "house"}), "PPSA04263-house")

    def test_machines_are_combined_only_within_a_scene(self):
        info = {"gpu": "NVIDIA GeForce RTX 5060 Laptop GPU", "os": "Linux 7.2.8", "driver": "NVIDIA 615.71.09"}
        sides = {"A": {"p50": [79.1, 79.0]}, "B": {"p50": [73.8, 74.0]}}
        results = {"one": {"status": "done", "class": info, "titles": {"PPSA04263": {"sides": sides}}},
                   "two": {"status": "done", "class": info, "titles": {"PPSA04263": {"sides": sides, "scene_id": "house"}}}}
        keys = sorted(verdict.by_class(results, "PPSA04263"))
        self.assertEqual(len(keys), 2)
        self.assertTrue(keys[1].endswith(" in house"))
        self.assertEqual({c["n"] for c in verdict.by_class(results, "PPSA04263").values()}, {1})

    def test_the_result_format_takes_a_scene_id(self):
        self.assertTrue(formats.SCENE_ID.fullmatch("vinewood-house"))
        self.assertFalse(formats.SCENE_ID.fullmatch("Vinewood house"))

    def test_the_config_file_keeps_the_scene(self):
        config = helpers.make_config()
        config.titles["PPSA04263"].scene = "house"
        configfile.save(config)
        self.assertEqual(configs.load(config.path).titles["PPSA04263"].scene, "house")


if __name__ == "__main__":
    unittest.main()
