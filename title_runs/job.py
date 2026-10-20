"""One job: a followed PR's head, built as GitHub's merge ref and as main at the merge's base, run on the tester's titles."""

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
    out.mkdir(parents=True, exist_ok=True)
    argv = sandbox.command(config.sandbox, [str(executable)], work, read_only=[title.dump, work / "app0", work / "libs", executable],
                           writable=[work, out])
    wrapper = work / "sandboxed"
    wrapper.write_text("#!/bin/sh\nexec " + shlex.join(argv) + ' "$@"\n')
    wrapper.chmod(0o755)
    machine, runs = {}, []
    with title_environment():
        for number in (1, 2):
            result = title_run.run_title(wrapper, work, out / f"run{number}", title.boot_seconds, title.env)
            for key in ("os", "gpu", "driver", "cpu"):
                machine[key] = machine.get(key) or result.pop(key)
            runs.append({"run": number, "cache": "cold" if number == 1 else "warm", **result})
            log(f"title_run run{number}: {result['outcome']}{' (' + result['first_error'] + ')' if result.get('first_error') else ''}")
    (out / "runs.json").write_text(json.dumps(runs, indent=2, default=str))
    return {"name": found["name"], "version": found["version"], "machine": machine, "runs": runs, "outcome": title_run.worst(runs)}


def run(config, state_dir, number, head, log):
    """Build and run; returns the job's results (also written to jobs/<number>-<head>/results.json)."""
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
        fetched_head, merge, base = sources.fetch_pr(config.repo_dir, config.remote, number)
        if fetched_head != head:
            results.update(status="superseded", detail=f"the PR's head is now {fetched_head[:9]}")
            return finish(job_dir, results)
        results.update(merge=merge, base=base)
        note(f"#{number} head {head[:9]}, merge {merge[:9]}, base {base[:9]}")
        trees = {"A": state_dir / "trees" / "main", "B": state_dir / "trees" / "pr"}
        commits = {"A": base, "B": merge}
        builds = {}
        for key in ("A", "B"):
            sources.worktree(config.repo_dir, trees[key], commits[key])
            pins = sources.submodules(config.repo_dir, trees[key], commits[key])
            build_dir = state_dir / "builds" / ("main" if key == "A" else "pr")
            note(f"{key}: building {commits[key][:9]} ({len(pins)} submodules)")
            builds[key] = {"dir": build_dir, **build.build(trees[key], build_dir, config.cmake_args, job_dir / f"build-{key}.log", commits[key])}
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
                base_line = f"main {base[:9]}; PR #{number} head {head[:9]} merged as {merge[:9]}"
                measure = protocol.Protocol(config, title, route, state_dir / "runs" / title_id, sides, note, base_line)
                ab = measure.ab(f"pr{number}-{head[:7]}")
                entry.update(ab=ab, verdict=protocol.verdict(ab.get("runs", [])), runs_dir=str(state_dir / "runs" / title_id))
                entry["outcome"] = outcome_of(ab)
            else:
                entry["scene"] = f"boot, {title.boot_seconds} s (no route)"
                for key, label in (("A", "main"), ("B", "pr")):
                    boot = boot_and_classify(config, title, builds[key]["dir"], state_dir / "games" / title_id / label,
                                             job_dir / f"boot-{title_id}-{label}", note)
                    entry.setdefault("boot", {})[key] = boot
                    entry.setdefault("name", boot["name"])
                    entry.setdefault("version", boot["version"])
                entry["outcome"] = {key: entry["boot"][key]["outcome"] for key in ("A", "B")}
        results["status"] = "done"
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
