"""One job: an approved commit of a PR, merged onto current main locally and built beside that main, both in the build
sandbox, then run on the tester's titles in the title sandbox."""

import contextlib
import datetime
import json
import os
import shlex
import subprocess
import traceback
from pathlib import Path

from . import build, game, protocol, route as routes, sandbox, sources
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
    """Build and run head (the approved SHA); returns the job's results (also written to jobs/<number>-<head>/results.json).

    recheck() -> a reason or None, called after the trees are ready and just before anything is built: the client asks
    the queue again whether this SHA is still the approved one. progress(text) and should_stop() go to the A/B protocol:
    a job whose head is superseded ends after the run it is in. remote: where the head and main come from (default the
    config's); main: a main SHA pinned in advance (the overnight list's), instead of main's tip now."""
    state_dir = Path(state_dir)
    job_dir = state_dir / "jobs" / f"{number}-{head[:12]}"
    job_dir.mkdir(parents=True, exist_ok=True)
    results = {"pr": number, "head": head, "started": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
               "machine": config.machine, "sandbox": config.sandbox, "titles": {}}

    def note(text):
        log(text)
        with open(job_dir / "job.log", "a") as stream:
            stream.write(f"{datetime.datetime.now():%H:%M:%S} {text}\n")

    try:
        remote = remote or config.remote
        base = sources.fetch_pinned(config.repo_dir, remote, head, main) if main else sources.fetch_approved(config.repo_dir, remote, head)
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
        # The last check before anything is built: the tree merges exactly the approved SHA, and the queue still names it.
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
            if title.route:
                route = routes.load(title.route)
                entry.update(scene=route["scene"], route=str(title.route))
                sides = []
                for key, label in (("A", "main"), ("B", "pr")):
                    work = state_dir / "games" / title_id / label
                    executable, found = game.prepare(title, builds[key]["dir"], work)
                    entry.setdefault("name", found["name"])
                    entry.setdefault("version", found["version"])
                    sides.append(protocol.Side(key, label, commits[key], executable, work, builds[key]["dir"], trees["A"] / "tools",
                                               state_dir / "caches" / title_id / label, run_env_rules(trees[key])))
                base_line = f"main {base[:9]}; PR #{number} approved {head[:9]} merged onto it locally as {merge[:9]}"
                measure = protocol.Protocol(config, title, route, state_dir / "runs" / title_id, sides, note, base_line)
                measure.progress, measure.should_stop = progress, should_stop
                ab = measure.ab(f"pr{number}-{head[:7]}")
                if ab.get("stopped"):
                    results.update(status="superseded", detail=ab["stopped"])
                entry.update(ab=ab, verdict=protocol.verdict(ab.get("runs", [])), runs_dir=str(state_dir / "runs" / title_id))
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


def finish(job_dir, results):
    results["finished"] = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
    (job_dir / "results.json").write_text(json.dumps(results, indent=2, default=str))
    return results
