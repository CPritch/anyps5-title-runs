"""The measurement for titles with a route: the harness's protocol (bench.sh, ab.sh), on sandboxed runs.

Per side (A = main at the merge base, B = GitHub's merge of the PR):
  - a warm-up only when no earlier run of the same built commit and RUN_ENV reached the scene on this machine
    (capture.py warmed). It runs the whole route, then stays in the scene until its last 60 s built no pipelines
    (capture.py quiet), at most 20 minutes, so a cold cache is filled before anything is timed;
  - one window for both sides from the latest warm runs' settle points (capture.py window), 60 s or as many presents
    as fit a trace of about TRACE_TARGET bytes, whichever is fewer (trace_presents): the project's performance form asks
    for each trace attached, and GitHub takes files up to 25 MB;
  - timed runs in the order A B A B, two per side: APS5_TRACE_FRAMES and APS5_TRACE_EVENTS only, the log on a
    pseudo-terminal (script(1)), frame dumps that stop before the window; each checked by capture.py check
    (counts / not counted), a run that does not count repeated once;
  - main's tools/trace_digest.py on each trace and tools/performance_compare.py on each pair.
A scenario with recorded play (scenarios.py, "input") plays it in every run from the first frame in its scene after
Resume Story (play_input); a run where that never happens doesn't count, and a warm-up waits for the play to end.
Run directories have the harness's layout (meta, actions, aps5-summary.jsonl, the trace, digest.txt, capture), so the
vendored capture.py reads them unchanged.
"""

import argparse
import contextlib
import datetime
import io
import json
import os
import shutil
import statistics
import subprocess
import sys
import threading
import time
from pathlib import Path

from . import VENDOR, pad, platform_info, route as routes, sandbox, scenarios, verdict as verdicts
from .game import Game

sys.path.insert(0, str(VENDOR / "gtav_harness"))
import capture  # noqa: E402

TRACE_EVENTS = 4194304
ATTACH_LIMIT = 25_000_000  # GitHub's largest attached file other than an image or a video (25 MB)
TRACE_TARGET = 20_000_000  # the size a window is chosen for, with room for a heavier stretch than any earlier trace had
BYTES_PER_PRESENT = 61_000  # without an earlier trace of the scenario: GTA V's heaviest so far (Franklin's house, 60.1 kB)
RECENT_TRACES = 8  # the window follows the scenario's last few traces (both sides of the last two tests), as main changes
WARM_HOLD_S = 30
WARM_MAX_S = 1200
SCENE_TIMEOUT_S = 600  # from Resume Story to the first frame in the scene: GTA V's loads take 80 s, or minutes cold
CAPTURE_TIMEOUT_S = 1500


def call(function, **kwargs):
    """Run one of capture.py's subcommands as a function; returns (exit code, stdout)."""
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        try:
            code = function(argparse.Namespace(**kwargs))
        except SystemExit as error:
            code = error.code if isinstance(error.code, int) else 1
            if not isinstance(error.code, int):
                print(error.code)
    return code or 0, out.getvalue()


class Side:
    def __init__(self, key, label, commit, executable, work, build_dir, tools, cache_dir, run_env):
        self.key, self.label, self.commit, self.executable, self.work = key, label, commit, Path(executable), Path(work)
        self.build_dir, self.tools, self.cache_dir, self.run_env = Path(build_dir), Path(tools), Path(cache_dir), dict(run_env)

    @property
    def run_env_text(self):
        return " ".join(f"{k}={v}" for k, v in sorted(self.run_env.items())) or "(none)"


class Protocol:
    def __init__(self, config, title, route, runs_dir, sides, log, base_line="", scenario=None):
        self.config, self.title, self.route, self.scenario = config, title, route, scenario
        self.machine_id = platform_info.machine_id()  # warm-ups belong to the computer, not to the name the tester gave it
        self.runs_dir, self.sides, self.log_line, self.base_line = Path(runs_dir), sides, log, base_line
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self.dump_every = route.get("dump_every", 30)

    def log(self, run, text):
        stamp = datetime.datetime.now().strftime("%H:%M:%S")
        with open(run / "actions", "a") as actions:
            actions.write(f"{stamp} {text}\n")
        self.log_line(f"{run.name}: {text}")

    def new_run(self, side, label):
        run = self.runs_dir / f"{datetime.datetime.now():%Y%m%d-%H%M%S}-{label}"
        run.mkdir(parents=True)
        lines = [f"started={datetime.datetime.now().isoformat(timespec='seconds')}", f"machine={self.machine_id}", f"display={sandbox.game_display()}",
                 f"built_from={side.commit}", f"run_env={side.run_env_text}", f"title={self.title.title_id}",
                 f"graphics={self.title.graphics_mode or '?'}", f"sandbox={self.config.sandbox}",
                 f"allocator={self.config.allocator or 'glibc'}", f"base={self.base_line}", f"side={side.key} {side.label}"]
        (run / "meta").write_text("\n".join(lines) + "\n")
        return run

    def meta(self, run, line):
        with open(run / "meta", "a") as meta:
            meta.write(line + "\n")

    def environment(self, side, run, extra):
        env = {
            "PATH": "/usr/bin:/bin", "LANG": os.environ.get("LANG", "C.UTF-8"),
            "SDL_AUDIODRIVER": "dummy", "SDL_GAMECONTROLLER_IGNORE_DEVICES_EXCEPT": "0x0000/0x0000", "APS5_NO_PAD_INPUT": "1",
            "SDL_VIDEO_WAYLAND_WMCLASS": "dev.anyps5.title-runs",
            "APS5_PAD_INPUT_FILE": str(side.work / "pad-input"),
            "ANYPS5_SHADER_CACHE_DIR": str(side.cache_dir / "anyps5"),
            "__GL_SHADER_DISK_CACHE_PATH": str(side.cache_dir / "driver"), "MESA_SHADER_CACHE_DIR": str(side.cache_dir / "driver"),
        }
        for key in ("DISPLAY", "WAYLAND_DISPLAY", "XDG_RUNTIME_DIR", "XAUTHORITY", "XDG_SESSION_TYPE"):
            if os.environ.get(key):
                env[key] = os.environ[key]
        if sandbox.wayland_socket():  # only Wayland's socket is in the sandbox (sandbox.display_binds)
            env.pop("DISPLAY", None)
            env.pop("XAUTHORITY", None)
        if sandbox.game_display() == "x11":
            # The app shows the game inside its window: an X11 window (XWayland on Wayland), which a Wayland window can't be.
            env.pop("WAYLAND_DISPLAY", None)
            env["SDL_VIDEODRIVER"] = "x11"
            env["XDG_SESSION_TYPE"] = "x11"
        env.update(self.title.env)
        env.update(side.run_env)
        env.update(extra)
        return env

    def launch(self, side, run, env, pty):
        for stale in [*side.work.glob("frame_*.bmp"), *side.work.glob("aps5-trace-*.json.gz"), side.work / "aps5-summary.jsonl", side.work / "pad-input"]:
            stale.unlink(missing_ok=True)
        (side.cache_dir / "anyps5").mkdir(parents=True, exist_ok=True)
        (side.cache_dir / "driver").mkdir(parents=True, exist_ok=True)
        read_only = [self.title.dump, side.work / "app0", side.work / "libs", side.executable]
        writable = [side.work, side.cache_dir, run]
        log = run / ("console.log" if pty else "game.log")
        game = Game(side.executable, side.work, run, env, self.config.sandbox, read_only, writable, pty=pty, log=log).start()
        self.log(run, f"started {side.executable.name} ({side.label} {side.commit[:9]}) in {'bubblewrap' if self.config.sandbox == 'bwrap' else 'NO sandbox'}")
        return game

    def driver(self, side, run, game):
        return routes.Driver(self.route, game, side.work, run, side.tools / "pad_input.py", side.work / "pad-input",
                             lambda text: self.log(run, "nav " + text))

    def stop(self, game, run):
        line = game.stop(self.config.shutdown_wait)
        self.log(run, "stop: " + line)
        return line

    def warmed(self, side):
        code, out = call(capture.warmed, runs_dir=str(self.runs_dir), machine=self.machine_id, built=side.commit, run_env=side.run_env_text)
        return out.strip() if code == 0 else None

    def warm_up(self, side):
        run = self.new_run(side, f"{side.label}-warm")
        env = self.environment(side, run, {"APS5_TRACE_SUMMARY_EVERY": "10", "APS5_DUMP_FRAMES": "100000",
                                           "APS5_DUMP_FRAMES_EVERY": str(self.dump_every), "APS5_TRACE_DIR": str(run)})
        self.meta(run, "capture=diagnostic warm-up")
        game = self.launch(side, run, env, pty=False)
        result = {"run": run.name, "reached": False}
        driver = self.driver(side, run, game)
        still = self.keep_still(side, run, game, driver)
        played = self.play_input(side, run, game, driver)
        try:
            marks = driver.run()
            loaded = marks.get("loaded", 0.0)
            self.meta(run, f"loaded_at={loaded} resume_at={marks.get('resume', 0.0)}")
            if played:
                limit = time.monotonic() + WARM_MAX_S  # the play's places warmed too: the window is in the middle of it
                while game.alive() and not (played["ended"] or played["problem"]) and time.monotonic() < limit:
                    time.sleep(2)
                if played["problem"]:
                    raise routes.RouteFailed(played["problem"])
            else:
                self.in_scene(side, run, latest(side.work))
            result["reached"] = True
            hold_end = time.monotonic() + WARM_HOLD_S
            while game.alive() and time.monotonic() < hold_end:
                time.sleep(2)
            limit = time.monotonic() + WARM_MAX_S
            quiet = ""
            while game.alive():
                code, quiet = call(capture.quiet, run=str(run), since=loaded, seconds=60)
                if code == 0:
                    break
                if time.monotonic() >= limit:
                    quiet = quiet.strip() + f"; stopped at WARM_MAX_S {WARM_MAX_S}"
                    break
                time.sleep(10)
            self.log(run, "warm-up: " + quiet.strip())
            self.meta(run, "warm_quiet=" + quiet.strip())
            result["quiet"] = quiet.strip()
        except routes.RouteFailed as error:
            self.log(run, f"route failed: {error}")
            result["route_failed"] = str(error)
        finally:
            if still:
                still.set()
            if played:
                played["stop"].set()
            result["stop"] = self.stop(game, run)
            result["exit_code"] = game.process.returncode
        if result["reached"]:
            call(capture.record, run=str(run))
        self.keep_last_frame(side, run)
        return result

    def keep_still(self, side, run, game, driver):
        """The scenario's still button (scenarios.py), pressed every few seconds from the route's resume mark (the load
        starting; warm-ups and timed runs alike) until the run stops, on a thread of its own. Returns the Event that
        stops it, or None."""
        still = (self.scenario or {}).get("still")
        if not still or (self.scenario or {}).get("input"):  # recorded play presses it after the play (play_input)
            return None
        stop = threading.Event()
        self.meta(run, f"still={still['press']} every {still['every']} s from resume")

        def press():
            while "resume" not in driver.marks:
                if stop.wait(1) or not game.alive():
                    return
            self.log(run, f"pressing {still['press']} every {still['every']} s ({still.get('why', 'the scenario asks for it')})")
            while not stop.wait(still["every"]) and game.alive():
                subprocess.run([sys.executable, "-I", str(side.tools / "pad_input.py"), str(side.work / "pad-input"), still["press"], "--hold-ms", "100"],
                               capture_output=True)
        threading.Thread(target=press, name="still", daemon=True).start()
        return stop

    def play_input(self, side, run, game, driver):
        """The scenario's recorded play (scenarios.py, "input"), on a thread of its own: from the first frame dumped after
        the route's resume mark that is in the scenario's scene, the track (pad.play), then the still button until the
        run stops. Returns {"stop": the Event that stops it, "started", "ended", "problem"}, or None for a scenario with
        no recorded play."""
        played = (self.scenario or {}).get("input")
        if not played:
            return None
        state = {"stop": threading.Event(), "started": None, "ended": None, "problem": None}
        stop, track = state["stop"], played["track"]
        self.meta(run, f"input=recorded play ({pad.words(track)}) from the first frame in the scene after resume")

        def play():
            while "resume" not in driver.marks:
                if stop.wait(1) or not game.alive():
                    return
            found = self.wait_for_scene(side, game, time.time() - 1, stop)
            if found is None:
                if not stop.is_set():
                    state["problem"] = "the scene never showed after Resume Story, so the recorded play didn't start"
                    self.log(run, state["problem"])
                    self.meta(run, "input_started=no")
                return
            state["started"] = time.monotonic()
            self.meta(run, f"input_started=yes: {found}")
            self.log(run, f"playing the recorded play from here ({found})")
            out = pad.PadFile(side.work / "pad-input")
            played_ms = pad.play(track, out, stop.is_set)
            state["ended"] = time.monotonic()
            self.meta(run, f"input_played={played_ms} of {track[-1][0]} ms")
            still = self.scenario.get("still")
            while still and not stop.wait(still["every"]) and game.alive():
                out.write((pad.BUTTONS[still["press"]], 128, 128, 128, 128))
        threading.Thread(target=play, name="input", daemon=True).start()
        return state

    def wait_for_scene(self, side, game, after, stop, timeout=SCENE_TIMEOUT_S):
        """The scene check's words for the first frame dumped after `after` (a time.time()) that is in the scenario's
        scene, or None when none is within timeout seconds, or the game ends, or stop is set."""
        seen, deadline = set(), time.monotonic() + timeout
        while game.alive() and time.monotonic() < deadline and not stop.is_set():
            frame = latest(side.work)
            try:
                fresh = frame is not None and frame.name not in seen and frame.stat().st_mtime >= after
            except OSError:
                fresh = False
            if fresh:
                found, words = scenarios.check(self.scenario, frame)
                if found is not None:  # None: not readable yet (still being written); looked at again
                    seen.add(frame.name)
                if found:
                    return words
            stop.wait(0.5)
        return None

    def in_scene(self, side, run, frame):
        """Raises RouteFailed when the frame isn't the scenario's scene (scenarios.check); records the check in meta."""
        if not self.scenario:
            return
        found, words = scenarios.check(self.scenario, frame)
        self.meta(run, f"scenario={self.scenario['id']} scene_check={'yes' if found else 'unknown' if found is None else 'no'}: {words}")
        self.log(run, f"scenario {self.scenario['id']}: {'in the scene' if found else 'not checked' if found is None else 'NOT in the scene'} ({words})")
        if found is False:
            raise routes.RouteFailed(f"not the scene of {self.scenario['name']}: {words}")

    def keep_last_frame(self, side, run):
        frames = sorted(side.work.glob("frame_*.bmp"), key=lambda p: p.stat().st_mtime)
        if frames:
            shutil.copy2(frames[-1], run / "last-frame.bmp")

    def window(self):
        code, out = call(capture.window, runs_dir=str(self.runs_dir), machine=self.machine_id,
                         builds=[side.commit for side in self.sides], margin_s=30, seconds=60, dump_every=self.dump_every)
        if code != 0 or not out.strip():
            raise RuntimeError(f"no window: {out.strip()}")
        spec, limit, sources = out.split()[:3]
        start, count = (int(value) for value in spec.split(":"))
        fits, self.sized = trace_presents(self.runs_dir)
        return f"{start}:{min(count, fits)}", int(limit), sources

    sized = ""  # why the window has as many presents as it has (window())

    def window_record(self, window):
        return {"spec": window[0], "dump_limit": window[1], "from": window[2], "sized": self.sized}

    def timed(self, side, label, window, warmed_by):
        spec, limit, sources = window
        run = self.new_run(side, label)
        self.meta(run, f"capture=timed APS5_TRACE_FRAMES={spec} APS5_TRACE_EVENTS={TRACE_EVENTS} dump_limit={limit}")
        self.meta(run, f"window_from={sources}")
        self.meta(run, f"window_sized={self.sized}")
        self.meta(run, f"warmed_by={warmed_by}")
        self.meta(run, "log=terminal (script(1))")
        env = self.environment(side, run, {"APS5_TRACE_FRAMES": spec, "APS5_TRACE_EVENTS": str(TRACE_EVENTS),
                                           "APS5_DUMP_FRAMES": str(limit), "APS5_DUMP_FRAMES_EVERY": str(self.dump_every)})
        game = self.launch(side, run, env, pty=True)
        result = {"run": run.name, "side": side.key}
        driver = self.driver(side, run, game)
        still = self.keep_still(side, run, game, driver)
        played = self.play_input(side, run, game, driver)
        try:
            driver.run(stop_at=self.route.get("timed_stop_after", "resume"))
            waited = 0
            while game.alive() and not capture.window_line(side.work):
                time.sleep(2)
                waited += 2
                if waited >= CAPTURE_TIMEOUT_S:
                    self.log(run, f"no window summary after {waited} s")
                    break
            last = -1
            for _ in range(60):
                traces = list(side.work.glob("aps5-trace-*.json.gz"))
                size = traces[0].stat().st_size if traces else -1
                if size >= 0 and size == last:
                    break
                last = size
                time.sleep(2)
        except routes.RouteFailed as error:
            self.log(run, f"route failed: {error}")
            result["route_failed"] = str(error)
        finally:
            if still:
                still.set()
            if played:
                played["stop"].set()
            result["stop"] = self.stop(game, run)
            result["exit_code"] = game.process.returncode
        self.keep_last_frame(side, run)
        if played:  # the scene was checked when the play started; the run ends wherever the play went
            if not played["started"]:
                result["scene_failed"] = played["problem"] or "the recorded play didn't start before the run ended"
        else:
            try:
                self.in_scene(side, run, run / "last-frame.bmp")
            except routes.RouteFailed as error:
                result["scene_failed"] = str(error)
        for path in [side.work / "aps5-summary.jsonl", *side.work.glob("aps5-trace-*.json.gz")]:
            if path.exists():
                shutil.move(str(path), run / path.name)
        trace = next(iter(run.glob("aps5-trace-*.json.gz")), None)
        if trace:
            digest = subprocess.run([sys.executable, "-I", str(side.tools / "trace_digest.py"), str(trace)], capture_output=True, text=True)
            (run / "digest.txt").write_text(digest.stdout + digest.stderr)
        code, out = call(capture.check, run=str(run), dump_every=self.dump_every)
        if result.get("scene_failed"):
            code, out = 1, f"{out.strip()}; not the scene: {result['scene_failed']}\n"
        (run / "capture").write_text(out)
        result["capture"] = out.strip()
        result["counts"] = code == 0
        lines = capture.window_line(run)
        result["summary"] = lines[0] if len(lines) == 1 else None
        if code == 0:
            call(capture.record, run=str(run))
        self.log(run, out.strip())
        return result

    progress = None  # progress(text): what the job is doing ("main warm-up", "PR run 2/4"), for the client's tray
    should_stop = None  # should_stop() -> a reason, checked between runs: the job ends after the run it is in

    def ab(self, name):
        """Warm-ups as needed, one window, A B A B with one repeat per run that does not count."""
        warm = {}
        say = self.progress or (lambda text: None)
        stopped = self.should_stop or (lambda: None)  # checked before every game start: a stopped job starts nothing more
        for side in self.sides:
            stop = stopped()
            if stop:
                return {"warm": warm, "runs": [], "stopped": stop}
            by = self.warmed(side)
            if by:
                warm[side.key] = {"run": by, "warm": "already"}
            else:
                say(f"{'main' if side.key == 'A' else 'PR'} warm-up")
                result = self.warm_up(side)
                warm[side.key] = {**result, "warm": "warm-up"}
                if not result["reached"]:
                    return {"warm": warm, "runs": [], "error": f"side {side.key}: the warm-up did not reach the scene"
                            + (f" ({result['route_failed']})" if result.get("route_failed") else "")}
        window = self.window()
        runs = []
        for number, side in enumerate([self.sides[0], self.sides[1], self.sides[0], self.sides[1]]):
            stop = stopped()
            if stop:
                return {"warm": warm, "window": self.window_record(window), "runs": runs,
                        "pairs": self.pairs(runs), "stopped": stop}
            label = f"{name}-{side.key}{number // 2 + 1}"
            say(f"{'main' if side.key == 'A' else 'PR'} run {number // 2 + 1}, {number + 1}/4")
            result = self.timed(side, label, window, warm[side.key]["run"])
            if not result["counts"]:
                stop = stopped()
                if stop:  # a run the tester's Stop ended does not count, but is not repeated
                    runs.append(result)
                    return {"warm": warm, "window": self.window_record(window), "runs": runs,
                            "pairs": self.pairs(runs), "stopped": stop}
                retry = self.timed(side, label + "r", window, warm[side.key]["run"])
                retry["repeat_of"] = result["run"]
                runs.append(result)
                result = retry
            runs.append(result)
        return {"warm": warm, "window": self.window_record(window), "runs": runs,
                "pairs": self.pairs(runs)}

    def pairs(self, runs):
        counted = {"A": [r for r in runs if r["counts"] and r["side"] == "A"], "B": [r for r in runs if r["counts"] and r["side"] == "B"]}
        tool = self.sides[0].tools / "performance_compare.py"
        out = []
        for a, b in zip(counted["A"], counted["B"]):
            result = subprocess.run([sys.executable, "-I", str(tool), str(self.runs_dir / a["run"] / "aps5-summary.jsonl"),
                                     str(self.runs_dir / b["run"] / "aps5-summary.jsonl")], capture_output=True, text=True)
            out.append({"a": a["run"], "b": b["run"], "text": (result.stdout if result.returncode == 0 else result.stderr).strip()})
        return out


def trace_presents(runs_dir):
    """(presents, why): how many presents fit a trace of TRACE_TARGET bytes, in tens and at least 100, at the most bytes
    per present of the last RECENT_TRACES timed traces in runs_dir (a scenario's own runs; run folders are named by
    their start), else at BYTES_PER_PRESENT. A trace is one slice per draw stage, so its size follows the scene and the
    build: GTA V's prologue was 46 to 52 kB per present on mains of 2026-10-21 and 22, and 40 to 41.5 on 15e71dbe1."""
    per_present = []
    for trace in sorted(Path(runs_dir).glob("*/aps5-trace-*.json.gz")):
        lines = capture.window_line(trace.parent)
        if len(lines) == 1 and lines[0].get("presents"):
            per_present.append(trace.stat().st_size / lines[0]["presents"])
    recent = per_present[-RECENT_TRACES:]
    per = max(recent, default=0) or BYTES_PER_PRESENT
    presents = max(100, int(TRACE_TARGET / per) // 10 * 10)
    seen = len(recent)
    source = (f"the most of the last {seen} traces here" if seen > 1 else "the one earlier trace here") if seen else "with no earlier trace here"
    return presents, f"at most {presents} presents fit a {TRACE_TARGET / 1e6:.0f} MB trace at {per / 1000:.1f} kB per present, {source}"


def latest(work):
    frames = sorted(Path(work).glob("frame_*.bmp"), key=lambda p: p.stat().st_mtime)
    return frames[-1] if frames else None


def verdict(runs):
    """p50/p90/p99/GPU per side over counted runs, and the per-machine rule (verdict.machine): a difference counts when
    it is larger than both sides' spreads and than 1 % of main's p50."""
    sides = {}
    for key in ("A", "B"):
        summaries = [r["summary"] for r in runs if r.get("counts") and r.get("side") == key and r.get("summary")]
        if summaries:
            f = [s["frame_ms"] for s in summaries]
            sides[key] = {"p50": [x["p50"] for x in f], "p90": [x["p90"] for x in f], "p99": [x["p99"] for x in f],
                          "gpu": [s["gpu_busy_ms_per_present"] for s in summaries], "counted": len(summaries)}
    return {"sides": sides, **verdicts.machine(sides)}
