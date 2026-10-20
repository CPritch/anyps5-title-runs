"""Lay a title out for one side of a job, launch it in the sandbox, stop it cleanly.

The layout is #7264's: title_run.prepare() unwraps the package's SELFs, relinks with the title's flags (its
tools/titles.json), hard-links app0 and the build's libraries. What title_run does not do is added here, after it:
  - app0_skip: entries of the package left out of app0 (GTA V's dump has a fakelib/ directory the harness skips);
  - seed: files copied into the game directory before the first run (GTA V's save data with the Graphics Mode
    setting, _sd/ and _sd_mem/, and anyps5-entitlements.ini);
  - caches outside the game directory (ANYPS5_SHADER_CACHE_DIR and the NVIDIA and Mesa caches), because prepare()
    removes the game directory, and the warm caches must outlive it.
"""

import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

from . import VENDOR, sandbox

sys.path.insert(0, str(VENDOR / "title_run" / "tools"))
import title_run  # noqa: E402

PLATFORM = "linux"


def prepare(title, build_dir, work):
    """title_run.prepare plus our additions. Returns the relinked executable (work/<TITLE ID>)."""
    work = Path(work)
    found = title_run.discover([title.dump])
    if title.title_id not in found:
        raise FileNotFoundError(f"{title.dump}: no package with title ID {title.title_id}")
    entries = title_run.load_titles(VENDOR / "title_run" / "tools" / "titles.json")
    executable = title_run.prepare(title.title_id, found[title.title_id], entries.get(title.title_id, {}), PLATFORM, Path(build_dir), work)
    if executable is None:
        raise RuntimeError(f"relink failed: {(work / 'relink.log').read_text(errors='replace')[-500:]}")
    for skip in title.app0_skip:
        target = work / "app0" / skip
        if target.is_dir():
            shutil.rmtree(target)
        elif target.exists():
            target.unlink()
    for path in title.seed:
        destination = work / path.name
        if path.is_dir():
            shutil.copytree(path, destination, dirs_exist_ok=True)
        elif path.exists():
            shutil.copy2(path, destination)
    shutil.rmtree(work / "input", ignore_errors=True)
    return executable, found[title.title_id]


def descendants(pid):
    found, stack = [], [pid]
    while stack:
        current = stack.pop()
        try:
            children = Path(f"/proc/{current}/task/{current}/children").read_text().split()
        except OSError:
            continue
        for child in map(int, children):
            found.append(child)
            stack.append(child)
    return found


class Game:
    """One run of the title: launched in the sandbox in its own session; stopped with SIGINT (SDL turns it into the
    title's normal quit, which runs the driver's teardown and the pipeline cache save), SIGKILL after shutdown_wait."""

    def __init__(self, executable, work, run_dir, env, mode, read_only, writable, pty=False, log=None):
        self.executable, self.work, self.run_dir = Path(executable), Path(work), Path(run_dir)
        argv = [str(self.executable)]
        if pty:
            argv = ["script", "-qec", f"exec {self.executable}", "/dev/null"]
        self.argv = sandbox.command(mode, argv, self.work, read_only, writable, env if mode == "bwrap" else None)
        self.env = {**os.environ, **env} if mode == "none" else {key: os.environ[key] for key in ("PATH", "LANG") if key in os.environ}
        self.log = log or (self.run_dir / "game.log")
        self.started = None

    def start(self):
        self.out = open(self.log, "wb")
        self.process = subprocess.Popen(self.argv, cwd=self.work, env=self.env, stdout=self.out, stderr=subprocess.STDOUT,
                                        stdin=subprocess.DEVNULL, start_new_session=True,
                                        preexec_fn=lambda: __import__("resource").setrlimit(__import__("resource").RLIMIT_CORE, (0, 0)))
        self.started = time.monotonic()
        return self

    def title_pid(self):
        for pid in descendants(self.process.pid):
            try:
                if os.path.realpath(f"/proc/{pid}/exe") == str(self.executable.resolve()):
                    return pid
            except OSError:
                continue
        return None

    def alive(self):
        return self.process.poll() is None

    def stop(self, wait):
        """SIGINT to the title, then wait; SIGKILL to the whole session after `wait` seconds. Returns a stop line."""
        if not self.alive():
            return f"had exited (code {self.process.returncode})"
        pid = self.title_pid()
        sent = time.monotonic()
        if pid:
            os.kill(pid, signal.SIGINT)
        else:
            os.killpg(self.process.pid, signal.SIGINT)
        while self.alive() and time.monotonic() - sent < wait:
            time.sleep(1)
        if self.alive():
            os.killpg(self.process.pid, signal.SIGKILL)
            self.process.wait()
            line = f"SIGKILL {wait} s after SIGINT"
        else:
            line = f"exited on its own {time.monotonic() - sent:.0f} s after SIGINT; no SIGKILL"
        self.out.close()
        return line
