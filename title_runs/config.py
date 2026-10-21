"""The tester's configuration file (TOML): what to follow, whom to trust, where the dumps are, how to run them."""

import os
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from . import ROOT

TITLE_ID = re.compile(r"[A-Z]{4}[0-9]{5}")


# When work may run (the Schedule tab): only when the machine has been idle idle_minutes, only on mains power, within
# hours [first, last), not while one of pause_for (process names) runs; and limits.
SCHEDULE = {"idle_only": True, "idle_minutes": 10, "mains_only": True, "hours": [0, 24], "pause_for": ["gtav.elf", "gtav-play"],
            "pause_fullscreen": True, "max_disk_gb": 60, "max_job_hours": 3}


class ConfigError(ValueError):
    pass


def results_location(text):
    """What a tester types for the results repository, as the URL the client clones: OWNER/NAME and
    https://github.com/OWNER/NAME become https://github.com/OWNER/NAME.git; other URLs and local paths stay as they are.
    There is no built-in default (DESIGN.md, round 4 decision 1)."""
    text = (text or "").strip()
    found = re.fullmatch(r"(?:https://github\.com/)?([A-Za-z0-9-]+/[A-Za-z0-9._-]+?)(?:\.git)?/?", text)
    if found and (text.startswith("https://github.com/") or not text.startswith(("/", ".", "~"))):
        return f"https://github.com/{found.group(1)}.git"
    return os.path.expanduser(text)


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


@dataclass
class Config:
    path: Path
    state_dir: Path
    repo: str
    github_client: str
    github_token_env: str
    budget_reserve: int
    remote: str
    tester: str
    machine: str
    follow_prs: list
    auto_unblocks: bool
    follow_labels: list
    include_drafts: bool
    authors: list
    maintainer_labels: list
    debounce_minutes: int
    repo_dir: Path
    cmake_args: list
    sandbox: str
    shutdown_wait: int
    titles: dict
    poster_enabled: bool
    poster_token_env: str
    allocator: str = ""
    results_url: str = ""
    results_github: str = "github"
    schedule: dict = field(default_factory=lambda: dict(SCHEDULE))
    screenshots: bool = False
    machine_info: dict = field(default_factory=dict)

    @property
    def owner(self):
        return self.repo.split("/", 1)[0]

    @property
    def name(self):
        return self.repo.split("/", 1)[1]


def load(path):
    path = Path(path).resolve()
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    github = data.get("github", {})
    tester = data.get("tester", {})
    follow = data.get("follow", {})
    trust = data.get("trust", {})
    poll = data.get("poll", {})
    source = data.get("source", {})
    sandbox = data.get("sandbox", {})
    poster = data.get("poster", {})
    repo = github.get("repo", "boykopovar/AnyPS5")
    if repo.count("/") != 1:
        raise ConfigError(f"github.repo {repo!r} is not owner/name")
    client = github.get("client", "gh")
    if client not in ("gh", "token"):
        raise ConfigError(f"github.client must be gh or token, not {client!r}")
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
                                 int(entry["boot_seconds"]) if "boot_seconds" in entry else None)
    for number in follow.get("prs", []):
        if not isinstance(number, int) or number < 1:
            raise ConfigError(f"follow.prs: {number!r} is not a PR number")
    return Config(
        path=path,
        state_dir=_path(data.get("state_dir", ROOT / "state")),
        repo=repo,
        github_client=client,
        github_token_env=github.get("token_env", "TITLE_RUNS_GITHUB_TOKEN"),
        budget_reserve=int(github.get("budget_reserve", 500)),
        remote=source.get("remote", "origin"),
        tester=tester.get("name", ""),
        machine=tester.get("machine", os.uname().nodename),
        follow_prs=list(follow.get("prs", [])),
        auto_unblocks=bool(follow.get("auto_unblocks", False)),
        follow_labels=list(follow.get("labels", [])),
        include_drafts=bool(follow.get("include_drafts", False)),
        authors=list(trust.get("authors", [])),
        maintainer_labels=list(trust.get("maintainer_labels", [])),
        debounce_minutes=int(poll.get("debounce_minutes", 10)),
        repo_dir=_path(source.get("repo_dir", "~/src/AnyPS5")),
        cmake_args=list(source.get("cmake_args", ["-G", "Ninja", "-DCMAKE_BUILD_TYPE=Release"])),
        sandbox=mode,
        shutdown_wait=int(sandbox.get("shutdown_wait", 900)),
        titles=titles,
        poster_enabled=bool(poster.get("enabled", False)),
        poster_token_env=poster.get("token_env", "TITLE_RUNS_BOT_TOKEN"),
        allocator=data.get("run", {}).get("allocator", ""),
        results_url=os.path.expanduser(data.get("results", {}).get("url", "")),
        results_github=data.get("results", {}).get("github", "github"),
        schedule={**SCHEDULE, **data.get("schedule", {})},
        screenshots=bool(data.get("client", {}).get("screenshots", False)),
        machine_info=dict(data.get("machine", {})),
    )
