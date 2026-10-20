"""The measurement for titles with a route: the harness's protocol (bench.sh, ab.sh), on sandboxed runs.

Per side (A = main at the merge base, B = GitHub's merge of the PR):
  - a warm-up only when no earlier run of the same built commit and RUN_ENV reached the scene on this machine
    (capture.py warmed). It runs the whole route, then stays in the scene until its last 60 s built no pipelines
    (capture.py quiet), at most 20 minutes, so a cold cache is filled before anything is timed;
  - one window for both sides from the latest warm runs' settle points (capture.py window);
  - timed runs in the order A B A B, two per side: APS5_TRACE_FRAMES and APS5_TRACE_EVENTS only, the log on a
    pseudo-terminal (script(1)), frame dumps that stop before the window; each checked by capture.py check
    (counts / not counted), a run that does not count repeated once;
  - main's tools/trace_digest.py on each trace and tools/performance_compare.py on each pair.
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
import time
from pathlib import Path

from . import VENDOR, route as routes
from .game import Game

sys.path.insert(0, str(VENDOR / "gtav_harness"))
import capture  # noqa: E402

TRACE_EVENTS = 4194304
WARM_HOLD_S = 30
WARM_MAX_S = 1200
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
    def __init__(self, config, title, route, runs_dir, sides, log, base_line=""):
        self.config, self.title, self.route = config, title, route
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
        lines = [f"started={datetime.datetime.now().isoformat(timespec='seconds')}", f"machine={self.config.machine}",
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
        code, out = call(capture.warmed, runs_dir=str(self.runs_dir), machine=self.config.machine, built=side.commit, run_env=side.run_env_text)
        return out.strip() if code == 0 else None

    def warm_up(self, side):
        run = self.new_run(side, f"{side.label}-warm")
        env = self.environment(side, run, {"APS5_TRACE_SUMMARY_EVERY": "10", "APS5_DUMP_FRAMES": "100000",
                                           "APS5_DUMP_FRAMES_EVERY": str(self.dump_every), "APS5_TRACE_DIR": str(run)})
        self.meta(run, "capture=diagnostic warm-up")
        game = self.launch(side, run, env, pty=False)
        result = {"run": run.name, "reached": False}
        try:
            marks = self.driver(side, run, game).run()
            loaded = marks.get("loaded", 0.0)
            self.meta(run, f"loaded_at={loaded} resume_at={marks.get('resume', 0.0)}")
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
            result["stop"] = self.stop(game, run)
            result["exit_code"] = game.process.returncode
        if result["reached"]:
            call(capture.record, run=str(run))
        self.keep_last_frame(side, run)
        return result

    def keep_last_frame(self, side, run):
        frames = sorted(side.work.glob("frame_*.bmp"), key=lambda p: p.stat().st_mtime)
        if frames:
            shutil.copy2(frames[-1], run / "last-frame.bmp")

    def window(self):
        code, out = call(capture.window, runs_dir=str(self.runs_dir), machine=self.config.machine,
                         builds=[side.commit for side in self.sides], margin_s=30, seconds=60, dump_every=self.dump_every)
        if code != 0 or not out.strip():
            raise RuntimeError(f"no window: {out.strip()}")
        spec, limit, sources = out.split()[:3]
        return spec, int(limit), sources

    def timed(self, side, label, window, warmed_by):
        spec, limit, sources = window
        run = self.new_run(side, label)
        self.meta(run, f"capture=timed APS5_TRACE_FRAMES={spec} APS5_TRACE_EVENTS={TRACE_EVENTS} dump_limit={limit}")
        self.meta(run, f"window_from={sources}")
        self.meta(run, f"warmed_by={warmed_by}")
        self.meta(run, "log=terminal (script(1))")
        env = self.environment(side, run, {"APS5_TRACE_FRAMES": spec, "APS5_TRACE_EVENTS": str(TRACE_EVENTS),
                                           "APS5_DUMP_FRAMES": str(limit), "APS5_DUMP_FRAMES_EVERY": str(self.dump_every)})
        game = self.launch(side, run, env, pty=True)
        result = {"run": run.name, "side": side.key}
        try:
            self.driver(side, run, game).run(stop_at=self.route.get("timed_stop_after", "resume"))
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
            result["stop"] = self.stop(game, run)
            result["exit_code"] = game.process.returncode
        self.keep_last_frame(side, run)
        for path in [side.work / "aps5-summary.jsonl", *side.work.glob("aps5-trace-*.json.gz")]:
            if path.exists():
                shutil.move(str(path), run / path.name)
        trace = next(iter(run.glob("aps5-trace-*.json.gz")), None)
        if trace:
            digest = subprocess.run([sys.executable, "-I", str(side.tools / "trace_digest.py"), str(trace)], capture_output=True, text=True)
            (run / "digest.txt").write_text(digest.stdout + digest.stderr)
        code, out = call(capture.check, run=str(run), dump_every=self.dump_every)
        (run / "capture").write_text(out)
        result["capture"] = out.strip()
        result["counts"] = code == 0
        lines = capture.window_line(run)
        result["summary"] = lines[0] if len(lines) == 1 else None
        if code == 0:
            call(capture.record, run=str(run))
        self.log(run, out.strip())
        return result

    def ab(self, name):
        """Warm-ups as needed, one window, A B A B with one repeat per run that does not count."""
        warm = {}
        for side in self.sides:
            by = self.warmed(side)
            if by:
                warm[side.key] = {"run": by, "warm": "already"}
            else:
                result = self.warm_up(side)
                warm[side.key] = {**result, "warm": "warm-up"}
                if not result["reached"]:
                    return {"warm": warm, "runs": [], "error": f"side {side.key}: the warm-up did not reach the scene"}
        window = self.window()
        runs = []
        for number, side in enumerate([self.sides[0], self.sides[1], self.sides[0], self.sides[1]]):
            label = f"{name}-{side.key}{number // 2 + 1}"
            result = self.timed(side, label, window, warm[side.key]["run"])
            if not result["counts"]:
                retry = self.timed(side, label + "r", window, warm[side.key]["run"])
                retry["repeat_of"] = result["run"]
                runs.append(result)
                result = retry
            runs.append(result)
        return {"warm": warm, "window": {"spec": window[0], "dump_limit": window[1], "from": window[2]}, "runs": runs,
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


def verdict(runs):
    """p50/p90/p99/GPU per side over counted runs, the difference, and the rule: a difference counts when it is larger
    than both sides' spreads (max - min of the side's p50s)."""
    sides = {}
    for key in ("A", "B"):
        summaries = [r["summary"] for r in runs if r.get("counts") and r.get("side") == key and r.get("summary")]
        if summaries:
            f = [s["frame_ms"] for s in summaries]
            sides[key] = {"p50": [x["p50"] for x in f], "p90": [x["p90"] for x in f], "p99": [x["p99"] for x in f],
                          "gpu": [s["gpu_busy_ms_per_present"] for s in summaries], "counted": len(summaries)}
    if len(sides) < 2 or any(v["counted"] < 2 for v in sides.values()):
        return {"sides": sides, "verdict": "not enough counted runs", "diff": None}
    a, b = sides["A"], sides["B"]
    diff = statistics.mean(b["p50"]) - statistics.mean(a["p50"])
    spread = max(capture.spread(a["p50"]), capture.spread(b["p50"]))
    if abs(diff) <= spread:
        kind = "no difference beyond the spread"
    else:
        kind = "faster" if diff < 0 else "slower"
    return {"sides": sides, "diff": diff, "diff_pct": diff / statistics.mean(a["p50"]) * 100, "spread": spread,
            "gpu_diff": statistics.mean(b["gpu"]) - statistics.mean(a["gpu"]), "verdict": kind}
