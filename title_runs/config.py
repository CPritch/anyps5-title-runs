"""The tester's configuration file (TOML): where the games and AnyPS5's source are, when to test, how to run, and the
local tests' project and pull requests."""

import os
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from . import ROOT

TITLE_ID = re.compile(r"[A-Z]{4}[0-9]{5}")


# When work may run (the Schedule tab): only when the machine has been idle idle_minutes, only on mains power, within
# hours [first, last), not while one of pause_for (process names) runs; and limits.
SCHEDULE = {"idle_only": True, "idle_minutes": 10, "mains_only": True, "hours": [0, 24], "pause_for": [],
            "pause_fullscreen": True, "max_disk_gb": 60, "max_job_hours": 3}


class ConfigError(ValueError):
    pass


def user_dirs():
    """(config, data) folders for this user: XDG on Linux, %APPDATA% and %LOCALAPPDATA% on Windows. The state (builds,
    caches, runs) goes in data, never in the tool's own folder, which a packaged release cannot write."""
    if os.name == "nt":
        config = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
        data = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    else:
        config = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
        data = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return config / "anyps5-title-runs", data / "anyps5-title-runs"


DEFAULT_CONFIG = user_dirs()[0] / "config.toml"


def _path(value):
    return Path(os.path.expanduser(str(value))).resolve() if value else None


@dataclass
class Title:
    title_id: str
    dump: Path
    route: Path | None = None
    seed: list = field(default_factory=list)
    app0_skip: list = field(default_factory=list)
    env: dict = field(default_factory=dict)
    graphics_mode: str = ""
    boot_seconds: int | None = None
    scenario: str = ""  # a scenario of scenarios/<TITLE ID>/ by id, or a scenario file's path; empty: the title's default (scenarios.py)


@dataclass
class Config:
    path: Path
    state_dir: Path
    remote: str
    machine: str
    repo_dir: Path
    cmake_args: list
    sandbox: str
    shutdown_wait: int
    titles: dict
    allocator: str = ""
    schedule: dict = field(default_factory=lambda: dict(SCHEDULE))
    testing: str = "schedule"  # the main screen's switch: off, schedule (within [schedule], while the app is open) or now (whatever it says)
    tray: bool = False  # keep running in the system tray when the window is closed (otherwise closing quits)
    text_size: str = "normal"
    view: str = "simple"
    local_repository: str = ""  # [local]: pull requests tested on this computer with nothing posted (local_tests.py)
    local_prs: list = field(default_factory=list)
    local_people: list = field(default_factory=list)
    local_fixes: list = field(default_factory=list)  # PRs merged onto main for both sides of local tests
    machine_info: dict = field(default_factory=dict)


TESTING = ("off", "schedule", "now")


def testing_mode(client):
    """The switch from [client]: testing, or the older automatic (true: On schedule)."""
    mode = client.get("testing")
    if mode in TESTING:
        return mode
    return "schedule" if client.get("automatic", True) else "off"


def load(path):
    path = Path(path).resolve()
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    tester = data.get("tester", {})
    source = data.get("source", {})
    sandbox = data.get("sandbox", {})
    local = data.get("local", data.get("overnight", {}))  # [overnight] until local tests had their name
    mode = sandbox.get("mode", "bwrap")
    if mode not in ("bwrap", "none"):
        raise ConfigError(f"sandbox.mode must be bwrap or none (none only when set explicitly), not {mode!r}")
    titles = {}
    for title_id, entry in data.get("titles", {}).items():
        if not TITLE_ID.fullmatch(title_id):
            raise ConfigError(f"titles.{title_id}: not a title ID")
        if "dump" not in entry:
            raise ConfigError(f"titles.{title_id}: no dump directory")
        route = entry.get("route")
        route_path = (ROOT / route).resolve() if route and not os.path.isabs(os.path.expanduser(route)) else _path(route)
        titles[title_id] = Title(title_id, _path(entry["dump"]), route_path, [_path(p) for p in entry.get("seed", [])],
                                 list(entry.get("app0_skip", [])), dict(entry.get("env", {})), entry.get("graphics_mode", ""),
                                 int(entry["boot_seconds"]) if "boot_seconds" in entry else None, str(entry.get("scenario", "")))
    return Config(
        path=path,
        state_dir=_path(data.get("state_dir", user_dirs()[1])),
        remote=source.get("remote", "origin"),
        machine=tester.get("machine", os.uname().nodename),
        repo_dir=_path(source.get("repo_dir", "")) or _path(data.get("state_dir", user_dirs()[1])) / "anyps5",
        cmake_args=list(source.get("cmake_args", ["-G", "Ninja", "-DCMAKE_BUILD_TYPE=Release"])),
        sandbox=mode,
        shutdown_wait=int(sandbox.get("shutdown_wait", 900)),
        titles=titles,
        allocator=data.get("run", {}).get("allocator", ""),
        schedule={**SCHEDULE, **data.get("schedule", {})},
        testing=testing_mode(data.get("client", {})),
        tray=bool(data.get("client", {}).get("tray", False)),
        text_size=str(data.get("client", {}).get("text_size", "normal")),
        view=str(data.get("client", {}).get("view", "simple")),
        local_repository=str(local.get("repository", "")),
        local_prs=[int(n) for n in local.get("prs", [])],
        local_people=[str(a) for a in local.get("people", local.get("authors", []))],
        local_fixes=[int(n) for n in local.get("fixes", [])],
        machine_info=dict(data.get("machine", {})),
    )
