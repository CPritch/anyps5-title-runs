"""Write a Config back as TOML: the setup window creates the tester's config file with it, and the Schedule and Settings
tabs save through it. A file written here has no hand-written comments; config.example.toml keeps those."""

from pathlib import Path


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
        if title.scenario:
            entry["scenario"] = title.scenario
        titles[title_id] = entry
    return {
        "state_dir": str(config.state_dir),
        "github": {"repo": config.repo, "client": config.github_client, "token_env": config.github_token_env, "budget_reserve": config.budget_reserve},
        "tester": {"name": config.tester, "machine": config.machine},
        "machine": dict(config.machine_info),
        "results": {"url": config.results_url, "github": config.results_github},
        "schedule": dict(config.schedule),
        "client": {"screenshots": config.screenshots, "testing": config.testing, "tray": config.tray, "text_size": config.text_size,
                   "view": config.view},
        "follow": {"prs": list(config.follow_prs), "auto_unblocks": config.auto_unblocks, "labels": list(config.follow_labels),
                   "include_drafts": config.include_drafts},
        "trust": {"authors": list(config.authors), "maintainer_labels": list(config.maintainer_labels)},
        "poll": {"debounce_minutes": config.debounce_minutes},
        "source": {"repo_dir": str(config.repo_dir), "remote": config.remote, "cmake_args": list(config.cmake_args)},
        "sandbox": {"mode": config.sandbox, "shutdown_wait": config.shutdown_wait},
        "run": {"allocator": config.allocator},
        "titles": titles,
        "local": {"repository": config.local_repository, "prs": list(config.local_prs), "people": list(config.local_people), "fixes": list(config.local_fixes)},
        "poster": {"enabled": config.poster_enabled, "token_env": config.poster_token_env},
    }


def save(config, path=None):
    path = Path(path or config.path)
    text = "# anyps5-title-runs: written by the title-runs window. config.example.toml explains every key.\n\n" + dumps(config_data(config))
    temporary = path.with_suffix(".tmp")
    temporary.write_text(text)
    temporary.replace(path)
    return path
