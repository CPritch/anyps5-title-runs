"""Scenarios: one specific run of a title, which may or may not load a save first.

Every timed run is in a scenario: how to get there (the route), what is on screen (the report's scene), and what makes
it the same every time. A scenario file:

  scenarios/<TITLE ID>/<id>.json
    {"title_id": "PPSA04263",
     "name": "Franklin's front door (100% save)",            the Games page's words
     "scene": "...",                                          the report's words for what is on screen, at most 120 characters
     "route": "routes/PPSA04263.json",                        how to get there
     "default": true,                                         the title's scenario when the config names none (optional)
     "save": {"about": "Apollo's PS4 100% save", "page": URL people open to get it,
              "url": the download, pinned to a commit, "sha256": of the download,
              "file": the member of a zip download that is the save (optional), "file_sha256": of that member,
              "into": {"memory_slot": 0}},                    where the title finds it (below; optional)
     "still": {"press": "left", "every": 10, "why": "..."},  a button pressed every few seconds from Resume Story (optional)
     "frame": {"colours": [64 shares], "max_distance": 0.3},  the scene's colours, which every run is checked against
     "input": {"track": [[ms, buttons, lx, ly, rx, ry], ...], recorded play, played from when the scene shows (optional)
               "from": the scenario it was recorded from, "recorded": {"at", "main", "controller"}}}

The save is downloaded once, outside the sandbox, checked against its sha256 and kept in <state>/saves/<sha256>/; it is
never stored in this repository (a save's licence is its source's). "into" says where AnyPS5 keeps it in the game
directory: memory_slot N is save-data memory, _sd_mem/u<user>/slot<N>.bin (libSceSaveData.native's mem_path), where
GTA V keeps its autosave on PS4 and reads it on PS5. Save directories (_sd/<name>/) are not supported yet.

"still" is for a title that moves its camera when nobody touches the controller: GTA V starts its idle camera after
about 30 s without input, and turns it differently on every boot, so the same save showed 64 to 119 ms frames depending
on where it looked. A button that does nothing where the scene is keeps it still; the report says which and how often.

What a still button can't fix: GTA V loads a save with its camera at a framing of its own choosing (11 boots of the
same save gave five; each boot then keeps its own), so runs in the house are not yet the same place every time.

"input" is play recorded from a controller (pad.py, recording.py; DESIGN.md, "Recorded play"): the scenario it was
recorded from, with the track every run plays back from the first frame in that scenario's scene (its "frame"), and
the still button after the track ends. The scene is checked when the track starts, not at the end of the run, which is
wherever the play went. Recorded scenarios are the tester's, kept in <state>/scenarios/<TITLE ID>/<id>.json next to
this tool's own (recorded()); a tool's scenario of the same id comes first.

A scenario's runs are kept apart from the title's others (runs_name()), so a warm-up in one never counts as warm for
another, and the timed window comes from the scenario's own settle point.

check() tells whether a run is in the scene and not another (a save the title didn't load starts a new game, and GTA V
then plays the prologue; a story save in the seed loads instead of the prologue). It compares colours, which stay when
the camera moves; a black frame is never in the scene.
"""

import hashlib
import io
import json
import re
import sys
import urllib.request
import zipfile
from pathlib import Path

from . import ROOT, VENDOR, pad

sys.path.insert(0, str(VENDOR / "gtav_harness"))
import frame_state  # noqa: E402

SCENARIOS = ROOT / "scenarios"
SCENARIO_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,39}")
SHA256 = re.compile(r"[0-9a-f]{64}")
USER = 268435456  # AnyPS5's first user (libSceUserService USER_SERVICE_INITIAL_USER_ID, 0x10000000)
MEMORY_MAX = 32 * 1024 * 1024  # libSceSaveData.native MEM_MAX_SIZE
BINS = 4  # colour levels per channel in check()'s comparison
BUTTONS = {"left": "D-pad left", "right": "D-pad right", "up": "D-pad up", "down": "D-pad down", "l3": "L3", "r3": "R3",
           "cross": "Cross", "circle": "Circle", "square": "Square", "triangle": "Triangle", "l1": "L1", "r1": "R1",
           "l2": "L2", "r2": "R2"}  # main's tools/pad_input.py names, as the report words them


class ScenarioError(ValueError):
    pass


def load(path):
    """A scenario file, checked: its id is the file's name."""
    path = Path(path)
    try:
        scenario = json.loads(path.read_text())
    except (OSError, ValueError) as error:
        raise ScenarioError(f"{path}: {error}") from error
    scenario["id"] = path.stem
    if not SCENARIO_ID.fullmatch(scenario["id"]):
        raise ScenarioError(f"{path}: the file name is not a scenario id (a-z, 0-9 and -)")
    for key in ("title_id", "name", "scene", "route"):
        if not isinstance(scenario.get(key), str) or not scenario[key]:
            raise ScenarioError(f"{path}: no {key}")
    if len(scenario["scene"]) > 120:
        raise ScenarioError(f"{path}: scene is over 120 characters")
    route = Path(scenario["route"])
    scenario["route"] = route if route.is_absolute() else ROOT / route
    save = scenario.get("save")
    if save is not None:
        if not str(save.get("url", "")).startswith("https://"):
            raise ScenarioError(f"{path}: save.url is not an https URL")
        for key in ("sha256",) + (("file_sha256",) if save.get("file") else ()):
            if not SHA256.fullmatch(str(save.get(key, ""))):
                raise ScenarioError(f"{path}: save.{key} is not a sha256")
        slot = (save.get("into") or {}).get("memory_slot")
        if not isinstance(slot, int) or not 0 <= slot < 16:
            raise ScenarioError(f"{path}: save.into names no memory_slot (0 to 15); save directories are not supported yet")
    still = scenario.get("still")
    if still is not None and (still.get("press") not in BUTTONS or not 5 <= still.get("every", 0) <= 25):
        raise ScenarioError(f"{path}: still needs a button of pad_input.py and every between 5 and 25 seconds (the idle camera waits about 30)")
    frame = scenario.get("frame")
    if frame is not None and (len(frame.get("colours") or []) != BINS ** 3 or not 0 < frame.get("max_distance", 0) < 1):
        raise ScenarioError(f"{path}: frame needs {BINS ** 3} colours and a max_distance between 0 and 1")
    played = scenario.get("input")
    if played is not None:
        if not frame:
            raise ScenarioError(f"{path}: input needs the scene's colours (frame), to start from")
        try:
            pad.check_track(played.get("track") if isinstance(played, dict) else None)
        except pad.PadError as error:
            raise ScenarioError(f"{path}: input: {error}") from error
    return scenario


def recorded(state_dir, title_id):
    """The folder of a title's recorded scenarios in a state folder."""
    return Path(state_dir) / "scenarios" / title_id


def available(title_id, state_dir=None):
    """The scenarios for a title, by id, the default first: this tool's, then the ones recorded in state_dir."""
    found = {}
    folders = [SCENARIOS / title_id] + ([recorded(state_dir, title_id)] if state_dir else [])
    for folder in folders:
        for path in sorted(folder.glob("*.json")):
            if path.stem in found:
                continue
            try:
                found[path.stem] = load(path)
            except ScenarioError:
                continue
    return dict(sorted(found.items(), key=lambda item: not item[1].get("default")))


def of(title, state_dir=None):
    """The scenario a title runs in: the one its config names (scenario = "<id>" of this tool's or recorded in
    state_dir, or the path of a scenario file of the tester's own), else the title's default, else None (a title with
    a route and no scenarios times where it goes)."""
    if not title.scenario:
        return next((s for s in available(title.title_id).values() if s.get("default")), None)
    value = Path(title.scenario).expanduser()
    path = value if value.suffix == ".json" else SCENARIOS / title.title_id / f"{title.scenario}.json"
    if not path.exists() and value.suffix != ".json" and state_dir:
        path = recorded(state_dir, title.title_id) / f"{title.scenario}.json"
    if not path.exists():
        raise ScenarioError(f"{title.title_id}: no scenario {title.scenario!r} ({path})")
    scenario = load(path)
    if scenario["title_id"] != title.title_id:
        raise ScenarioError(f"{path}: a scenario of {scenario['title_id']}, not {title.title_id}")
    return scenario


def runs_name(title_id, scenario):
    """The runs folder of a title in a scenario, <TITLE ID>-<scenario id>; <TITLE ID> for a route with no scenario."""
    return title_id if scenario is None else f"{title_id}-{scenario['id']}"


def _sha256(data):
    return hashlib.sha256(data).hexdigest()


def fetch(save, cache, opener=urllib.request.urlopen):
    """The save's file, downloaded once and checked: <cache>/<sha256 of the file>/save.bin. Raises ScenarioError when the
    download or the zip member doesn't match its sha256."""
    want = save.get("file_sha256") or save["sha256"]
    kept = Path(cache) / want / "save.bin"
    if kept.exists() and _sha256(kept.read_bytes()) == want:
        return kept
    try:
        with opener(save["url"], timeout=120) as response:
            data = response.read(64 * 1024 * 1024 + 1)
    except OSError as error:
        raise ScenarioError(f"could not download the save {save['url']}: {error}") from error
    if _sha256(data) != save["sha256"]:
        raise ScenarioError(f"the save {save['url']} is not the one the scenario names (sha256 {_sha256(data)[:12]}, want {save['sha256'][:12]})")
    if save.get("file"):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                data = archive.read(save["file"])  # one named member, never extracted to a path
        except (KeyError, zipfile.BadZipFile) as error:
            raise ScenarioError(f"{save['url']}: no {save['file']} in it ({error})") from error
        if _sha256(data) != save["file_sha256"]:
            raise ScenarioError(f"{save['url']}: {save['file']} is not the one the scenario names")
    if len(data) > MEMORY_MAX:
        raise ScenarioError(f"the save is {len(data)} bytes, over AnyPS5's {MEMORY_MAX} for save-data memory")
    kept.parent.mkdir(parents=True, exist_ok=True)
    partial = kept.with_suffix(".part")
    partial.write_bytes(data)
    partial.replace(kept)
    return kept


def files(scenario, cache, opener=urllib.request.urlopen):
    """[(source, path in the game directory)] for game.prepare: the scenario's save where the title finds it."""
    if scenario is None or not scenario.get("save"):
        return []
    save = scenario["save"]
    source = fetch(save, cache, opener)
    return [(source, Path("_sd_mem") / f"u{USER}" / f"slot{save['into']['memory_slot']}.bin")]


def save_words(scenario):
    """The report's sentence on the save, so others can load the same one."""
    save = (scenario or {}).get("save")
    if not save:
        return ""
    member = f", its {Path(save['file']).name}" if save.get("file") else ""
    return (f"The save is {save['about']} ({save.get('page') or save['url']}{member}, sha256 {(save.get('file_sha256') or save['sha256'])[:12]}), "
            f"loaded as save-data memory slot {save['into']['memory_slot']} (_sd_mem/u{USER}/slot{save['into']['memory_slot']}.bin).")


def input_words(scenario):
    """The report's words for the input during a run in the scenario."""
    still = (scenario or {}).get("still")
    played = (scenario or {}).get("input")
    if played:
        when = str((played.get("recorded") or {}).get("at", ""))[:10]
        words = f"with input recorded from a controller{' on ' + when if when else ''} ({pad.words(played['track'])}), replayed from when the scene appeared"
        return words + (f", then {BUTTONS[still['press']]} every {still['every']} s" if still else "")
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


def check(scenario, frame):
    """(True | False | None, words): whether frame shows the scenario's scene. None when the scenario has no reference
    colours or there is no frame to look at."""
    reference = (scenario or {}).get("frame")
    if not reference:
        return None, "no reference colours for this scenario"
    if frame is None or not Path(frame).exists():
        return None, "no frame to check"
    try:
        pixels = frame_state.sample(str(frame))
        if frame_state.classify(pixels)[0] == "black":
            return False, f"{Path(frame).name} is black"
        distance = sum(abs(a - b) for a, b in zip(colours(frame), reference["colours"])) / 2
    except (SystemExit, OSError, IndexError) as error:
        return None, f"could not read {Path(frame).name}: {error}"
    words = f"{Path(frame).name} is {distance:.2f} from the scene's colours (at most {reference['max_distance']})"
    return distance <= reference["max_distance"], words
