"""The tester's client: the status file the window, the tray and the command line read (the test running, a Stop asked
for), the first-run walkthrough, and whether a test may start now.

Nothing runs until the tester has been through the walkthrough (ready()); then a test starts only when the schedule
allows it (allowed_now()), or whatever it says when testing is Now.
"""

import datetime
import json
import os
import re
from pathlib import Path

from . import formats, locks, platform_info

UNSAFE = re.compile(r"[<>`|\r\n\x00-\x08\x0b-\x1f]")


def clean(text, limit=120):
    return UNSAFE.sub(" ", str(text or ""))[:limit].strip()


class Status:
    """status.json: what the client does now, for the tray and the window; requests from them (pause, stop) too."""

    def __init__(self, path):
        self.path = Path(path)

    def read(self):
        try:
            return json.loads(self.path.read_text())
        except (OSError, json.JSONDecodeError):
            return {"state": "idle", "line": "Idle"}

    def update(self, **values):
        with locks.held(self.path):  # the window, the command line and the running test all write it
            data = self.read()
            data.update(values, updated=formats.iso(formats.now()))
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(json.dumps(data, indent=1))
            os.replace(temporary, self.path)
            return data


class Client:
    def __init__(self, config, log=print, info=None):
        self.config = config
        self.dir = Path(config.state_dir) / "client"

        def both(text):
            # The window's Logs box reads client.log, whether the client runs in the window or on the command line.
            self.dir.mkdir(parents=True, exist_ok=True)
            with open(self.dir / "client.log", "a") as stream:
                stream.write(f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S} {text}\n")
            log(text)

        self.log = both
        self.status = Status(self.dir / "status.json")
        self.info = info or config.machine_info or platform_info.machine_info()
        self.machine_class = formats.machine_class(self.info["gpu"], self.info["os"], self.info.get("driver", ""))
        for old in ("github-token.json", "github-token.json.lock"):  # the sign-in before 2026-10-23: nothing reads it now
            if (self.dir / old).exists():
                (self.dir / old).unlink()
                if old.endswith(".json"):
                    self.log("removed the old GitHub sign-in: the tool reads GitHub without one")

    # -- the walkthrough -----------------------------------------------------------------------------------------------

    def onboarded(self):
        return (self.dir / "onboarding.json").exists()

    def finish_onboarding(self, answers):
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "onboarding.json").write_text(json.dumps({"completed": formats.iso(formats.now()), **answers}, indent=1))

    def ready(self):
        """(True, "") once the tester has been through the walkthrough and has a game set up."""
        if not self.onboarded():
            return False, "the first-run walkthrough is not done"
        if not self.config.titles:
            return False, "no titles are set up"
        return True, ""

    def allowed_now(self, at=None):
        """(True, "") when work may start now: ready, and the schedule allows it."""
        ready, why = self.ready()
        if not ready:
            return False, why
        at = at or datetime.datetime.now().astimezone()
        rules = self.config.schedule
        paused = self.status.read().get("paused_until")
        if paused == "indefinitely" or (paused and formats.parse_time(paused) > at):
            return False, "paused" if paused == "indefinitely" else f"paused until {formats.parse_time(paused).astimezone():%H:%M}"
        first, last = rules.get("hours", [0, 24])
        if not first <= at.hour < last:
            return False, f"outside the hours {first:02d}-{last:02d}"
        if rules.get("mains_only", True) and platform_info.on_mains() is False:
            return False, "on battery"
        busy = platform_info.running(rules.get("pause_for", [])) + (["a fullscreen program"] if rules.get("pause_fullscreen", True) and platform_info.fullscreen() else [])
        if busy:
            return False, f"{', '.join(busy)} is running"
        if rules.get("idle_only", True) and platform_info.idle_detection()[0]:
            idle = platform_info.idle_seconds()
            if idle is not None and idle < 60 * rules.get("idle_minutes", 10):
                return False, f"in use (idle {idle / 60:.0f} of {rules.get('idle_minutes', 10)} min)"
        return True, ""
