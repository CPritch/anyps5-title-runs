"""Scenes: where a title is timed, and the save it loads to get there.

A title is timed in the scene its route reaches (routes/<TITLE ID>.json). For GTA V that is the prologue: with no story
save, Resume Story starts a new game. A scene file adds a save, so the same route loads a chosen place instead:

  scenes/<TITLE ID>/<id>.json
    {"title_id": "PPSA04263",
     "name": "Vinewood Hills house (100% save)",              the Titles page's words
     "scene": "...",                                          the report's words: what is on screen, at most 120 characters
     "route": "routes/PPSA04263.json",                        how to get there (the save is what makes it this scene)
     "save": {"about": "Apollo's PS4 100% save", "page": URL people open to get it,
              "url": the download, pinned to a commit, "sha256": of the download,
              "file": the member of a zip download that is the save (optional), "file_sha256": of that member,
              "into": {"memory_slot": 0}},                    where the title finds it (below)
     "still": {"press": "left", "every": 10, "why": "..."},  a button pressed every few seconds once the route is done
     "frame": {"colours": [64 shares], "from": "<run>/<frame>", "max_distance": 0.25}}   the loaded scene (check())

The save is downloaded once, outside the sandbox, checked against its sha256 and kept in <state>/saves/<sha256>/; it is
never stored in this repository (a save's licence is its source's). "into" says where AnyPS5 keeps it in the game
directory: memory_slot N is save-data memory, _sd_mem/u<user>/slot<N>.bin (libSceSaveData.native's mem_path), where
GTA V keeps its autosave on PS4 and reads it on PS5. Save directories (_sd/<name>/) are not supported yet.

"still" is for a title that moves its camera when nobody touches the controller: GTA V starts its idle camera after
about 30 s without input, and turns it differently on every boot, so the same save showed 64 to 119 ms frames depending
on where it looked. A button that does nothing where the scene is keeps it still; the report says which and how often.

A scene's runs are kept apart from the title's other scenes (runs_name()), so a warm-up in one scene never counts as
warm for another, and the timed window comes from the scene's own settle point.

check() tells whether a run reached the scene and not another one (a save the title didn't load starts a new game, and
GTA V then plays the prologue). It compares colours, not positions: with no input GTA V's camera turns away within a
minute, which moves most of the frame, but the colours of the place stay. On the first save boots (2026-10-22) frames
of the house stayed within 0.11 of the first loaded frame, and the prologue's bank was 0.42 away.
"""

import hashlib
import json
import re
import sys
import urllib.request
import zipfile
from pathlib import Path

from . import ROOT, VENDOR

sys.path.insert(0, str(VENDOR / "gtav_harness"))
import frame_state  # noqa: E402

SCENES = ROOT / "scenes"
SCENE_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,39}")
SHA256 = re.compile(r"[0-9a-f]{64}")
USER = 268435456  # AnyPS5's first user (libSceUserService USER_SERVICE_INITIAL_USER_ID, 0x10000000)
MEMORY_MAX = 32 * 1024 * 1024  # libSceSaveData.native MEM_MAX_SIZE
BINS = 4  # colour levels per channel in check()'s comparison
BUTTONS = {"left": "D-pad left", "right": "D-pad right", "up": "D-pad up", "down": "D-pad down", "l3": "L3", "r3": "R3",
           "cross": "Cross", "circle": "Circle", "square": "Square", "triangle": "Triangle", "l1": "L1", "r1": "R1",
           "l2": "L2", "r2": "R2"}  # main's tools/pad_input.py names, as the report words them


class SceneError(ValueError):
    pass


def load(path):
    """A scene file, checked: its id is the file's name."""
    path = Path(path)
    try:
        scene = json.loads(path.read_text())
    except (OSError, ValueError) as error:
        raise SceneError(f"{path}: {error}") from error
    scene["id"] = path.stem
    if not SCENE_ID.fullmatch(scene["id"]):
        raise SceneError(f"{path}: the file name is not a scene id (a-z, 0-9 and -)")
    for key in ("title_id", "name", "scene", "route"):
        if not isinstance(scene.get(key), str) or not scene[key]:
            raise SceneError(f"{path}: no {key}")
    if len(scene["scene"]) > 120:
        raise SceneError(f"{path}: scene is over 120 characters")
    route = Path(scene["route"])
    scene["route"] = route if route.is_absolute() else ROOT / route
    save = scene.get("save")
    if save is not None:
        if not str(save.get("url", "")).startswith("https://"):
            raise SceneError(f"{path}: save.url is not an https URL")
        for key in ("sha256",) + (("file_sha256",) if save.get("file") else ()):
            if not SHA256.fullmatch(str(save.get(key, ""))):
                raise SceneError(f"{path}: save.{key} is not a sha256")
        slot = (save.get("into") or {}).get("memory_slot")
        if not isinstance(slot, int) or not 0 <= slot < 16:
            raise SceneError(f"{path}: save.into names no memory_slot (0 to 15); save directories are not supported yet")
    still = scene.get("still")
    if still is not None and (still.get("press") not in BUTTONS or not 5 <= still.get("every", 0) <= 25):
        raise SceneError(f"{path}: still needs a button of pad_input.py and every between 5 and 25 seconds (the idle camera waits about 30)")
    frame = scene.get("frame")
    if frame is not None and (len(frame.get("colours") or []) != BINS ** 3 or not 0 < frame.get("max_distance", 0) < 1):
        raise SceneError(f"{path}: frame needs {BINS ** 3} colours and a max_distance between 0 and 1")
    return scene


def available(title_id):
    """The scenes this tool has for a title, by id."""
    found = {}
    for path in sorted((SCENES / title_id).glob("*.json")):
        try:
            found[path.stem] = load(path)
        except SceneError:
            continue
    return found


def of(title):
    """The scene a title is set to (config: scene = "<id>" or a path to a scene file of the tester's own), or None."""
    if not title.scene:
        return None
    value = Path(title.scene).expanduser()
    path = value if value.suffix == ".json" else SCENES / title.title_id / f"{title.scene}.json"
    if not path.exists():
        raise SceneError(f"{title.title_id}: no scene {title.scene!r} ({path})")
    scene = load(path)
    if scene["title_id"] != title.title_id:
        raise SceneError(f"{path}: a scene of {scene['title_id']}, not {title.title_id}")
    return scene


def runs_name(title_id, scene):
    """The runs folder of a title in a scene: <TITLE ID> for its route alone, <TITLE ID>-<scene id> with a save."""
    return title_id if scene is None else f"{title_id}-{scene['id']}"


def _sha256(data):
    return hashlib.sha256(data).hexdigest()


def fetch(save, cache, opener=urllib.request.urlopen):
    """The save's file, downloaded once and checked: <cache>/<sha256 of the file>/save.bin. Raises SceneError when the
    download or the zip member doesn't match its sha256."""
    want = save.get("file_sha256") or save["sha256"]
    kept = Path(cache) / want / "save.bin"
    if kept.exists() and _sha256(kept.read_bytes()) == want:
        return kept
    try:
        with opener(save["url"], timeout=120) as response:
            data = response.read(64 * 1024 * 1024 + 1)
    except OSError as error:
        raise SceneError(f"could not download the save {save['url']}: {error}") from error
    if _sha256(data) != save["sha256"]:
        raise SceneError(f"the save {save['url']} is not the one the scene names (sha256 {_sha256(data)[:12]}, want {save['sha256'][:12]})")
    if save.get("file"):
        import io
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                data = archive.read(save["file"])  # one named member, never extracted to a path
        except (KeyError, zipfile.BadZipFile) as error:
            raise SceneError(f"{save['url']}: no {save['file']} in it ({error})") from error
        if _sha256(data) != save["file_sha256"]:
            raise SceneError(f"{save['url']}: {save['file']} is not the one the scene names")
    if len(data) > MEMORY_MAX:
        raise SceneError(f"the save is {len(data)} bytes, over AnyPS5's {MEMORY_MAX} for save-data memory")
    kept.parent.mkdir(parents=True, exist_ok=True)
    partial = kept.with_suffix(".part")
    partial.write_bytes(data)
    partial.replace(kept)
    return kept


def files(scene, cache, opener=urllib.request.urlopen):
    """[(source, path in the game directory)] for game.prepare: the scene's save where the title finds it."""
    if scene is None or not scene.get("save"):
        return []
    save = scene["save"]
    source = fetch(save, cache, opener)
    return [(source, Path("_sd_mem") / f"u{USER}" / f"slot{save['into']['memory_slot']}.bin")]


def save_words(scene):
    """The report's sentence on the save, so others can load the same one."""
    save = (scene or {}).get("save")
    if not save:
        return ""
    member = f", its {Path(save['file']).name}" if save.get("file") else ""
    return (f"The save is {save['about']} ({save.get('page') or save['url']}{member}, sha256 {(save.get('file_sha256') or save['sha256'])[:12]}), "
            f"loaded as save-data memory slot {save['into']['memory_slot']} (_sd_mem/u{USER}/slot{save['into']['memory_slot']}.bin).")


def input_words(scene):
    """The report's words for the input during a run in the scene."""
    still = (scene or {}).get("still")
    if not still:
        return "with no input"
    why = f" ({still['why']})" if still.get("why") else ""
    return f"with {BUTTONS[still['press']]} pressed every {still['every']} s{why} and no other input"


def colours(frame):
    """The shares of a frame's sampled pixels (frame_state.sample, 96x54) in BINS^3 colour boxes."""
    pixels = frame_state.sample(str(frame))
    counts = [0] * BINS ** 3
    for r, g, b in pixels:
        counts[(r * BINS // 256) * BINS * BINS + (g * BINS // 256) * BINS + b * BINS // 256] += 1
    return [round(count / len(pixels), 4) for count in counts]


def check(scene, frame):
    """(True | False | None, words): whether frame shows the scene. None when the scene has no reference frame or there
    is no frame to look at."""
    reference = (scene or {}).get("frame")
    if not reference:
        return None, "no reference frame for this scene"
    if frame is None or not Path(frame).exists():
        return None, "no frame to check"
    try:
        distance = sum(abs(a - b) for a, b in zip(colours(frame), reference["colours"])) / 2
    except (SystemExit, OSError, IndexError) as error:
        return None, f"could not read {Path(frame).name}: {error}"
    words = f"{Path(frame).name} is {distance:.2f} from the scene's colours (at most {reference['max_distance']})"
    return distance <= reference["max_distance"], words
