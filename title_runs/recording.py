"""Recording a scenario (DESIGN.md, "Recorded play"): the game started on this computer's main build in a scenario, as
a run starts it, and from the first frame in that scenario's scene its start input played (as every run plays it), then
the tester's controller passed through to the game and recorded on the game's pad reads (pad.record), at rest for the
first second. The result is a new scenario: the one it started from (its route, save, start, still button and scene
colours) with the track, kept in <state>/scenarios/<TITLE ID>/<id>.json.

Main's build is the last local test's (<state>/builds/main, from <state>/trees/main): a local test builds it.
"""

import datetime
import json
import os
import re
import threading
import time
from pathlib import Path

from . import ROOT, game, job, pad, protocol, route as routes, scenarios, sources

MIN_SECONDS = 100  # the window opens about 30 s after the scene loads and lasts up to 60 s
DEFAULT_SECONDS = 150
MAX_SECONDS = 600


class RecordError(RuntimeError):
    pass


def new_id(name, taken=()):
    """A scenario id from its name: "Walk to the car" -> walk-to-the-car, with -2, -3 when taken."""
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:36].strip("-") or "recorded"
    found, number = base, 1
    while found in taken:
        number += 1
        found = f"{base}-{number}"
    return found


def check(config, title_id, base_id, scenario_id, name, scene, seconds):
    """The scenario recording starts from; raises RecordError for anything that would stop it before the game starts."""
    if title_id not in config.titles:
        raise RecordError(f"{title_id} is not one of your games")
    found = scenarios.available(title_id, config.state_dir)
    base = found.get(base_id)
    if base is None:
        raise RecordError(f"{title_id} has no scenario {base_id!r} to start from; it has {', '.join(found) or 'none'}")
    if base.get("input"):
        raise RecordError(f"{base['name']} has recorded play already: start from a scenario without it")
    if not base.get("frame"):
        raise RecordError(f"{base['name']} has no scene colours to start from")
    if not scenarios.SCENARIO_ID.fullmatch(scenario_id or ""):
        raise RecordError(f"{scenario_id!r} is not a scenario id (a-z, 0-9 and -, up to 40)")
    if scenario_id in found:
        raise RecordError(f"{title_id} has a scenario {scenario_id!r} already")
    if not name.strip() or not scene.strip() or len(scene) > 120:
        raise RecordError("a recording needs a name, and words for what happens in it (up to 120 characters)")
    if not MIN_SECONDS <= seconds <= MAX_SECONDS:
        raise RecordError(f"a recording is {MIN_SECONDS} to {MAX_SECONDS} seconds: the timed window opens about 30 s in and lasts up to 60")
    return base


def main_side(config, title, scenario):
    """Main's side as a run has it: the last local test's main build, the game folder prepared with the scenario's save."""
    state = Path(config.state_dir)
    tree, build_dir = state / "trees" / "main", state / "builds" / "main"
    if not (tree / ".git").exists() or not build_dir.is_dir():
        raise RecordError("main isn't built on this computer yet: a local test builds it, then you can record")
    commit = sources.git(tree, "rev-parse", "HEAD")
    work = state / "games" / title.title_id / "main"
    executable, _ = game.prepare(title, build_dir, work, scenarios.files(scenario, state / "saves"))
    return protocol.Side("A", "main", commit, executable, work, build_dir, tree / "tools", state / "caches" / title.title_id / "main",
                         job.run_env_rules(tree))


def session(config, title, base, seconds, controller, log, progress, should_stop):
    """Start the game in base on main, wait for its scene, record the controller. Returns (track, main's commit)."""
    side = main_side(config, title, base)
    route = routes.load(base["route"])
    folder = Path(config.state_dir) / "recordings"
    measure = protocol.Protocol(config, title, route, folder, [side], log, scenario=base)
    run = measure.new_run(side, f"{title.title_id}-record")
    env = measure.environment(side, run, {"APS5_TRACE_SUMMARY_EVERY": "10", "APS5_DUMP_FRAMES": "100000",
                                          "APS5_DUMP_FRAMES_EVERY": str(measure.dump_every), "APS5_TRACE_DIR": str(run)})
    measure.meta(run, f"capture=recording from {base['id']} for {seconds} s with {controller.name}")
    progress("starting the game")
    running = measure.launch(side, run, env, pty=False)
    gone = threading.Event()

    def stopping():
        return should_stop() or (None if running.alive() else "the game ended")

    try:
        progress("getting to the scene")
        measure.driver(side, run, running).run(stop_at="resume")
        found = measure.wait_for_scene(side, running, time.time() - 1, gone)
        if found is None:
            raise RecordError(stopping() or "the scene never showed after Resume Story")
        out = pad.PadFile(side.work / "pad-input")
        with pad.PadReads(out.path) as reads:
            start = base.get("start")
            if start:
                progress("hands off: setting the camera")
                measure.log(run, f"playing the start input from here ({found})")
                pad.play(start["track"], out, reads, stopping)
            measure.log(run, "recording from here")
            track = pad.record(controller, out, reads, seconds, stopping,
                               progress=lambda second: progress(f"play now: {second} of {seconds} s" if second >= 1 else "hands off for a second"))
        measure.keep_last_frame(side, run)
    except routes.RouteFailed as error:
        raise RecordError(f"the game didn't get to the scene: {error}") from error
    finally:
        gone.set()
        measure.stop(running, run)
    why = should_stop()
    if why:
        raise RecordError(f"{why}: nothing was saved")
    if track[-1][0] < MIN_SECONDS * 1000:
        raise RecordError(f"the recording ended after {track[-1][0] / 1000:.0f} s ({stopping() or 'stopped'}): nothing was saved")
    return track, side.commit


def save(config, title_id, base, scenario_id, name, scene, track, commit, controller_name, at=None):
    """The new scenario's file: base with the track."""
    route = Path(base["route"])
    data = {"title_id": title_id, "name": name.strip(), "scene": scene.strip(),
            "route": str(route.relative_to(ROOT)) if route.is_relative_to(ROOT) else str(route),
            "source": f"recorded from {base['name']} on main {commit[:9]}"}
    for key in ("save", "start", "still", "frame"):
        if base.get(key):
            data[key] = base[key]
    data["input"] = {"from": base["id"], "recorded": {"at": (at or datetime.datetime.now(datetime.timezone.utc)).isoformat(timespec="seconds"),
                                                      "main": commit, "controller": controller_name}, "track": track}
    folder = scenarios.recorded(config.state_dir, title_id)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{scenario_id}.json"
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, indent=1))
    os.replace(temporary, path)
    scenarios.load(path)  # as every run will read it
    return path


def record(config, title_id, base_id, scenario_id, name, scene, seconds, controller, log=print, progress=print, should_stop=lambda: None):
    """Record a scenario: check, play, save. Returns the new scenario file's path; raises RecordError, or pad.PadError
    when the controller goes."""
    base = check(config, title_id, base_id, scenario_id, name, scene, seconds)
    track, commit = session(config, config.titles[title_id], base, seconds, controller, log, progress, should_stop)
    return save(config, title_id, base, scenario_id, name, scene, track, commit, controller.name)
