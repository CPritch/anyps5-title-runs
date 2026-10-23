"""One job: a PR's head, merged onto main locally and built beside that main, both in the build sandbox, then run on the
tester's titles in the title sandbox."""

import contextlib
import datetime
import itertools
import json
import os
import shlex
import subprocess
import traceback
from pathlib import Path

from . import build, game, protocol, route as routes, sandbox, scenarios, sources
from .game import title_run


RULES = Path(__file__).with_name("run_env_rules.json")


def run_env_rules(tree):
    """Switches a build needs on every run (run_env_rules.json, from the harness's run-env-rules.txt): each rule applies
    when its commit is in the tree's history."""
    found = {}
    for rule in json.loads(RULES.read_text()):
        if subprocess.run(["git", "-C", str(tree), "merge-base", "--is-ancestor", rule["commit"], "HEAD"], capture_output=True).returncode == 0:
            found.update(rule["set"])
    return found


TITLE_ENV = ("PATH", "LANG", "DISPLAY", "WAYLAND_DISPLAY", "XDG_RUNTIME_DIR", "XAUTHORITY", "XDG_SESSION_TYPE")


@contextlib.contextmanager
def title_environment():
    """title_run.run_title passes os.environ on to the title: keep only what a title needs (no tokens) for the call."""
    saved = dict(os.environ)
    os.environ.clear()
    os.environ.update({key: saved[key] for key in TITLE_ENV if key in saved})
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(saved)


def boot_and_classify(config, title, build_dir, work, out, log):
    """#7264's generic run for a title without a route: title_run.run_title, unchanged, twice (cold, then warm). Its
    Session starts an executable, so the executable it is given is a wrapper that starts the relinked title in the
    sandbox (bwrap passes the environment run_title builds on to the title)."""
    executable, found = game.prepare(title, build_dir, work)
    seconds = title.boot_seconds or game.title_entry(title.title_id).get("seconds", 60)
    out.mkdir(parents=True, exist_ok=True)
    argv = sandbox.command(config.sandbox, [str(executable)], work, read_only=[title.dump, work / "app0", work / "libs", executable],
                           writable=[work, out])
    wrapper = work / "sandboxed"
    wrapper.write_text("#!/bin/sh\nexec " + shlex.join(argv) + ' "$@"\n')
    wrapper.chmod(0o755)
    machine, runs = {}, []
    with title_environment():
        for number in (1, 2):
            result = title_run.run_title(wrapper, work, out / f"run{number}", seconds, title.env)
            for key in ("os", "gpu", "driver", "cpu"):
                machine[key] = machine.get(key) or result.pop(key)
            runs.append({"run": number, "cache": "cold" if number == 1 else "warm", **result})
            log(f"title_run run{number}: {result['outcome']}{' (' + result['first_error'] + ')' if result.get('first_error') else ''}")
    (out / "runs.json").write_text(json.dumps(runs, indent=2, default=str))
    return {"name": found["name"], "version": found["version"], "seconds": seconds, "machine": machine, "runs": runs,
            "outcome": title_run.worst(runs)}


def run(config, state_dir, number, head, log, recheck=None, progress=None, should_stop=None, remote=None, main=None):
    """Build and run head (a PR's head SHA); returns the job's results (also written to the job's folder, job_folder()).

    recheck() -> a reason or None, called after the trees are ready and just before anything is built (local tests:
    whether the tester pressed Stop). progress(text) and should_stop() go to the A/B protocol: a job asked to stop ends
    after the run it is in. remote: where the head and main come from (default the config's); main: a main SHA pinned in
    advance (local tests'), instead of main's tip now.

    Each title runs in its scenario (scenarios.py): a save is downloaded and checked before anything is built, and the
    job's folder is named after the scenario too, so a head tested in two scenarios keeps both results."""
    state_dir = Path(state_dir)
    try:
        chosen, unknown = {title_id: scenarios.of(title, state_dir) for title_id, title in config.titles.items()}, None
    except scenarios.ScenarioError as error:  # failed below, in the job's own folder
        chosen, unknown = {title_id: None for title_id in config.titles}, error
    job_dir = job_folder(state_dir / "jobs", f"{number}-{head[:12]}" + "".join(f"-{scenario['id']}" for scenario in chosen.values() if scenario))
    results = {"pr": number, "head": head, "started": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
               "machine": config.machine, "sandbox": config.sandbox, "titles": {}, "job": job_dir.name}

    def note(text):
        log(text)
        with open(job_dir / "job.log", "a") as stream:
            stream.write(f"{datetime.datetime.now():%H:%M:%S} {text}\n")

    try:
        if unknown:
            raise unknown
        saves = {}
        for title_id, scenario in chosen.items():
            saves[title_id] = scenarios.files(scenario, state_dir / "saves")
            if scenario:
                note(f"{title_id}: the scenario {scenario['name']}" + (", the save checked against its sha256" if saves[title_id] else ""))
        remote = remote or config.remote
        base = sources.fetch_pinned(config.repo_dir, remote, head, main) if main else sources.fetch_head(config.repo_dir, remote, head)
        trees = {"A": state_dir / "trees" / "main", "B": state_dir / "trees" / "pr"}
        sources.worktree(config.repo_dir, trees["A"], base)
        sources.worktree(config.repo_dir, trees["B"], base)
        merge = sources.merge_onto(trees["B"], base, head)
        results.update(merge=merge, base=base)
        note(f"#{number}: {head[:9]} merged onto main {base[:9]} as {merge[:9]}")
        commits = {"A": base, "B": merge}
        for key in ("A", "B"):
            pins = sources.submodules(config.repo_dir, trees[key], commits[key], remote)
            note(f"{key}: {commits[key][:9]}, {len(pins)} submodules filled")
        # The last check before anything is built: the tree merges exactly head, and nothing asked the job to stop.
        built = sources.git(trees["B"], "rev-parse", "HEAD^2")
        stop = f"the tree to build merges {built[:9]}, not {head[:9]}" if built != head else (recheck() if recheck else None)
        if stop:
            results.update(status="superseded", detail=stop)
            note(f"not built: {stop}")
            return finish(job_dir, results)
        builds = {}
        for key in ("A", "B"):
            build_dir = state_dir / "builds" / ("main" if key == "A" else "pr")
            note(f"{key}: building {commits[key][:9]} in the {config.sandbox} build sandbox")
            builds[key] = {"dir": build_dir, **build.build(trees[key], build_dir, config.cmake_args, job_dir / f"build-{key}.log", commits[key], config.sandbox)}
            note(f"{key}: built in {builds[key]['seconds']} s, {builds[key]['prx']} prx, shader cache version {builds[key]['shader_cache_version']}")
        results["builds"] = {key: {k: str(v) for k, v in value.items()} for key, value in builds.items()}
        for title_id, title in config.titles.items():
            entry = {"title_id": title_id}
            results["titles"][title_id] = entry
            scenario = chosen[title_id]
            if title.route or scenario:
                route = routes.load(scenario["route"] if scenario else title.route)
                entry.update(scene=scenario["scene"] if scenario else route["scene"], route=str(scenario["route"] if scenario else title.route))
                if scenario:
                    entry.update(scenario=scenario["id"], save=scenarios.save_words(scenario), input=scenarios.input_words(scenario))
                runs_dir = state_dir / "runs" / scenarios.runs_name(title_id, scenario)
                sides = []
                for key, label in (("A", "main"), ("B", "pr")):
                    work = state_dir / "games" / title_id / label
                    executable, found = game.prepare(title, builds[key]["dir"], work, saves[title_id])
                    entry.setdefault("name", found["name"])
                    entry.setdefault("version", found["version"])
                    sides.append(protocol.Side(key, label, commits[key], executable, work, builds[key]["dir"], trees["A"] / "tools",
                                               state_dir / "caches" / title_id / label, run_env_rules(trees[key])))
                base_line = f"main {base[:9]}; PR #{number} at {head[:9]} merged onto it locally as {merge[:9]}"
                measure = protocol.Protocol(config, title, route, runs_dir, sides, note, base_line, scenario=scenario)
                measure.progress, measure.should_stop = progress, should_stop
                ab = measure.ab(f"pr{number}-{head[:7]}")
                if ab.get("stopped"):
                    results.update(status="superseded", detail=ab["stopped"])
                entry.update(ab=ab, verdict=protocol.verdict(ab.get("runs", [])), runs_dir=str(runs_dir))
                entry["outcome"] = outcome_of(ab)
            else:
                for key, label in (("A", "main"), ("B", "pr")):
                    boot = boot_and_classify(config, title, builds[key]["dir"], state_dir / "games" / title_id / label,
                                             job_dir / f"boot-{title_id}-{label}", note)
                    entry.setdefault("boot", {})[key] = boot
                    entry.setdefault("name", boot["name"])
                    entry.setdefault("version", boot["version"])
                entry["scene"] = f"boot, {entry['boot']['A']['seconds']} s (no route)"
                entry["outcome"] = {key: entry["boot"][key]["outcome"] for key in ("A", "B")}
        results.setdefault("status", "done")
    except Exception as error:
        results["status"] = "failed"
        results["error"] = f"{type(error).__name__}: {error}"
        (job_dir / "error.txt").write_text(traceback.format_exc())
        note(f"failed: {results['error']}")
    return finish(job_dir, results)


def outcome_of(ab):
    """The outcome class per side for a routed title, in #7264's terms: rendering when every timed run of the side
    produced its window; otherwise crashed or exited (the title had ended, by its exit code) or stalled (still alive,
    the route stuck), with the route's failure."""
    out = {}
    for key in ("A", "B"):
        runs = [ab.get("warm", {}).get(key, {})] + [r for r in ab.get("runs", []) if r.get("side") == key]
        failed = next((r for r in runs if r.get("route_failed")), None)
        if failed:
            stop = failed.get("stop", "")
            if stop.startswith("had exited"):
                kind = "crashed" if failed.get("exit_code") not in (0, None) else "exited"
            else:
                kind = "stalled"
            out[key] = f"{kind} ({failed['route_failed']})"
        elif any(r.get("side") == key for r in ab.get("runs", [])):
            timed = [r for r in ab["runs"] if r.get("side") == key]
            out[key] = "rendering" if all(r.get("summary") for r in timed) else "stalled (no window summary)"
        else:
            out[key] = "not run"
    return out


def job_folder(jobs, name):
    """A new job's folder: jobs/<name>, or <name>-2, -3 and on when an earlier test of the same head in the same scenarios
    finished in it (results.json), so each test keeps its own results (Test again on the Local tests page). A folder
    without results.json, from a job that never finished, is used again."""
    for number in itertools.count(1):
        path = Path(jobs) / (name if number == 1 else f"{name}-{number}")
        if not (path / "results.json").exists():
            path.mkdir(parents=True, exist_ok=True)
            return path


def finish(job_dir, results):
    results["finished"] = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
    (job_dir / "results.json").write_text(json.dumps(results, indent=2, default=str))
    return results
