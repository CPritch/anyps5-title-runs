"""Write a Config back as TOML: the setup window creates the tester's config file with it, and the Schedule and Settings
tabs save through it. A file written here has no hand-written comments; config.example.toml keeps those.

change() is the command line's way to change a setting while the window may be open: the file is read, changed and
written under the config's lock, and the window merges what changed (engine.Engine.sync_config)."""

import copy
import dataclasses
from pathlib import Path

from . import locks


def _value(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_value(v) for v in value) + "]"
    if isinstance(value, dict):
        return "{ " + ", ".join(f"{_key(k)} = {_value(v)}" for k, v in value.items()) + " }"
    if isinstance(value, Path):
        value = str(value)
    if not isinstance(value, str):
        raise TypeError(f"cannot write {type(value).__name__} as TOML")
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


def _key(key):
    return key if key.replace("_", "").replace("-", "").isalnum() else _value(key)


def dumps(data):
    """TOML for {key: value or {section: ...}}: plain values first, then [sections], then [a.b] sub-sections."""
    lines = []
    for key, value in data.items():
        if not isinstance(value, dict):
            lines.append(f"{_key(key)} = {_value(value)}")
    for key, value in data.items():
        if isinstance(value, dict):
            plain = {k: v for k, v in value.items() if not (isinstance(v, dict) and k != "env")}
            nested = {k: v for k, v in value.items() if isinstance(v, dict) and k != "env"}
            if plain or not nested:
                lines += ["", f"[{_key(key)}]"] + [f"{_key(k)} = {_value(v)}" for k, v in plain.items()]
            for sub, table in nested.items():
                lines += ["", f"[{_key(key)}.{_key(sub)}]"] + [f"{_key(k)} = {_value(v)}" for k, v in table.items()]
    return "\n".join(lines).lstrip() + "\n"


def config_data(config):
    """The TOML structure of a Config (the sections config.load reads)."""
    titles = {}
    for title_id, title in config.titles.items():
        entry = {"dump": str(title.dump)}
        if title.route:
            entry["route"] = str(title.route)
        if title.seed:
            entry["seed"] = [str(p) for p in title.seed]
        if title.app0_skip:
            entry["app0_skip"] = list(title.app0_skip)
        if title.graphics_mode:
            entry["graphics_mode"] = title.graphics_mode
        if title.env:
            entry["env"] = dict(title.env)
        if title.boot_seconds:
            entry["boot_seconds"] = title.boot_seconds
        if title.scenarios:
            entry["scenarios"] = list(title.scenarios)
        titles[title_id] = entry
    return {
        "state_dir": str(config.state_dir),
        "tester": {"machine": config.machine},
        "machine": dict(config.machine_info),
        "schedule": dict(config.schedule),
        "client": {"testing": config.testing, "tray": config.tray, "game_in_window": config.game_in_window, "text_size": config.text_size,
                   "view": config.view},
        "source": {"repo_dir": str(config.repo_dir), "remote": config.remote, "cmake_args": list(config.cmake_args)},
        "sandbox": {"mode": config.sandbox, "shutdown_wait": config.shutdown_wait},
        "run": {"allocator": config.allocator},
        "titles": titles,
        "local": {"repository": config.local_repository, "prs": list(config.local_prs), "people": list(config.local_people), "fixes": list(config.local_fixes)},
    }


def change(path, edit):
    """Load the config file, edit(config), save it, under the config's lock. Returns the config."""
    from . import config as configs
    with locks.held(Path(path).resolve()):
        config = configs.load(path)
        edit(config)
        save(config)
    return config


def snapshot(config):
    """The config's settings as they are now (deep copies), to tell later which of them this process changed."""
    return {f.name: copy.deepcopy(getattr(config, f.name)) for f in dataclasses.fields(config) if f.name != "path"}


def merge(config, base, disk):
    """Take every setting another process changed on disk (disk differs from base, what this process last read or
    wrote) unless this process changed it too; returns the names taken."""
    taken = []
    for name, value in base.items():
        theirs = getattr(disk, name)
        if theirs != value and getattr(config, name) == value:
            setattr(config, name, copy.deepcopy(theirs))
            taken.append(name)
    return taken


def save(config, path=None):
    path = Path(path or config.path)
    text = "# anyps5-title-runs: written by the title-runs window. config.example.toml explains every key.\n\n" + dumps(config_data(config))
    temporary = path.with_suffix(".tmp")
    temporary.write_text(text)
    temporary.replace(path)
    return path
