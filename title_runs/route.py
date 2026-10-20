"""Title routes as data: pad steps and frame-state conditions to a named scene, as the harness's nav.sh does.

A route file (routes/<TITLE ID>.json) holds the scene's name and a list of steps. The interpreter waits on the dumped
frames (APS5_DUMP_FRAMES in the game directory) classified by the harness's frame_state.py, presses pad buttons through
main's tools/pad_input.py (the APS5_PAD_INPUT_FILE protocol), and reads the 10 s summaries with steady.py.

Steps:
  {"wait": {"state": S}, "timeout": T}                 until the latest frame is in state S
  {"wait": {"stable": S, "checks": N}, "timeout": T}   until it has been in S for N checks in a row (1 s apart)
  {"press": B, "until": C, "within": T, "tries": K}    press B, wait up to T s for C; retry up to K times
      C: {"left": S} (out of S for two checks in a row), {"state": S}, {"change": true} (a newer frame differs visibly)
  {"if": C, "within": T, "then": [steps]}              run the steps only when C happens within T s
  {"repeat": N, "steps": [steps]}
  {"sleep": seconds}, {"log": text}
  {"mark": name}                                       remember the summaries' clock (seconds after the first present)
  {"loaded": {"after": mark, "max_p50_ms": P, "not_state": S}, "timeout": T}
      until two 10 s summaries after the mark each have p50 <= P and max < 5 x p50, and the frame is not in S
A step's "fail" text is logged when it times out, and the route stops there.
"""

import json
import subprocess
import sys
import time
from pathlib import Path

from . import VENDOR

sys.path.insert(0, str(VENDOR / "gtav_harness"))
import frame_state  # noqa: E402
import steady  # noqa: E402


class RouteFailed(RuntimeError):
    pass


def load(path):
    route = json.loads(Path(path).read_text())
    for key in ("title_id", "scene", "steps"):
        if key not in route:
            raise ValueError(f"{path}: no {key}")
    return route


class Driver:
    def __init__(self, route, game, work, run_dir, pad_tool, pad_file, log):
        self.route, self.game, self.work, self.run_dir = route, game, Path(work), Path(run_dir)
        self.pad_tool, self.pad_file, self.log = pad_tool, pad_file, log
        self.marks = {}

    def latest(self):
        frames = sorted(self.work.glob("frame_*.bmp"), key=lambda p: p.stat().st_mtime)
        return frames[-1] if frames else None

    def state(self):
        frame = self.latest()
        if frame is None:
            return None
        try:
            return frame_state.classify(frame_state.sample(str(frame)))[0]
        except (SystemExit, OSError, IndexError):
            return None

    def differs(self, a, b):
        pa, pb = frame_state.sample(str(a)), frame_state.sample(str(b))
        changed = sum(1 for p, q in zip(pa, pb) if sum(abs(x - y) for x, y in zip(p, q)) > 24)
        return changed / len(pa) > 0.02

    def summary_now(self):
        rows = steady.intervals(str(self.run_dir / "aps5-summary.jsonl"))
        return rows[-1]["interval_end_s"] if rows else 0.0

    def press(self, button):
        subprocess.run([sys.executable, "-I", str(self.pad_tool), str(self.pad_file), button, "--hold-ms", "100"], check=True, capture_output=True)
        self.log(f"pad {button} --hold-ms 100")

    def wait(self, test, timeout):
        waited = 0
        while self.game.alive():
            if test():
                return True
            time.sleep(1)
            waited += 1
            if waited >= timeout:
                return False
        return False

    def condition(self, condition, within, reference=None):
        if "state" in condition:
            return self.wait(lambda: self.state() == condition["state"], within)
        if "left" in condition:
            streak = [0]

            def left():
                now = self.state()
                streak[0] = streak[0] + 1 if now is not None and now != condition["left"] else 0
                return streak[0] >= 2
            return self.wait(left, within)
        if "change" in condition:
            return self.wait(lambda: (lambda now: now is not None and now != reference and reference is not None and self.differs(reference, now))(self.latest()), within)
        if "stable" in condition:
            streak = [0]

            def stable():
                streak[0] = streak[0] + 1 if self.state() == condition["stable"] else 0
                return streak[0] >= condition.get("checks", 1)
            return self.wait(stable, within)
        raise ValueError(f"unknown condition {condition}")

    def run(self, steps=None, stop_at=None):
        """Run the route's steps; stop after the mark named stop_at. Returns the marks."""
        for step in steps if steps is not None else self.route["steps"]:
            if "wait" in step:
                if not self.condition(step["wait"], step.get("timeout", 60)):
                    raise RouteFailed(step.get("fail", f"timed out: {step}"))
            elif "press" in step:
                for attempt in range(1, step.get("tries", 1) + 1):
                    reference = self.latest()
                    self.press(step["press"])
                    if self.condition(step["until"], step.get("within", 10), reference):
                        break
                    self.log(f"no response to {step['press']} (try {attempt})")
                else:
                    raise RouteFailed(step.get("fail", f"{step['press']} had no effect"))
            elif "if" in step:
                if self.condition(step["if"], step.get("within", 5)):
                    self.run(step["then"])
            elif "repeat" in step:
                for _ in range(step["repeat"]):
                    self.run(step["steps"])
            elif "sleep" in step:
                time.sleep(step["sleep"])
            elif "log" in step:
                self.log(step["log"])
            elif "mark" in step:
                self.marks[step["mark"]] = self.summary_now()
                self.log(f"{step['mark']} at {self.marks[step['mark']]:.1f} s")
                if step["mark"] == stop_at:
                    return self.marks
            elif "loaded" in step:
                spec = step["loaded"]
                after = self.marks.get(spec.get("after"), 0.0)
                limit = spec.get("max_p50_ms", 1000)

                def settled():
                    if spec.get("not_state") and self.state() == spec["not_state"]:
                        return False
                    rows = [r for r in steady.intervals(str(self.run_dir / "aps5-summary.jsonl")) if r["interval_start_s"] >= after]
                    last = rows[-2:]
                    return len(last) == 2 and all(r["frame_ms"]["p50"] <= limit and r["frame_ms"]["max"] < 5 * r["frame_ms"]["p50"] for r in last)
                if not self.wait(settled, step.get("timeout", 900)):
                    if not self.game.alive():
                        raise RouteFailed("the title stopped during the load")
                    self.log(f"not steady after {step.get('timeout', 900)} s; continuing")
            else:
                raise ValueError(f"unknown step {step}")
        return self.marks
