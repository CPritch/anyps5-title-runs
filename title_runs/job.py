"""One job: a followed PR's head, built as GitHub's merge ref and as main at the merge's base, run on the tester's titles."""

import datetime
import json
import os
import subprocess
import sys
import traceback
from pathlib import Path

from . import VENDOR, build, game, protocol, route as routes, sandbox, sources


RULES = Path(__file__).with_name("run_env_rules.json")


def run_env_rules(tree):
    """Switches a build needs on every run (run_env_rules.json, from the harness's run-env-rules.txt): each rule applies
    when its commit is in the tree's history."""
    found = {}
    for rule in json.loads(RULES.read_text()):
        if subprocess.run(["git", "-C", str(tree), "merge-base", "--is-ancestor", rule["commit"], "HEAD"], capture_output=True).returncode == 0:
            found.update(rule["set"])
    return found


def boot_and_classify(config, title, side_tree, build_dir, out, log):
    """#7264's generic run, inside the sandbox: title_run.py boots the title twice (cold, then warm) and classifies."""
    runner = VENDOR / "title_run" / "tools" / "title_run.py"
    out.mkdir(parents=True, exist_ok=True)
    argv = [sys.executable, "-I", str(runner), "--games", str(title.dump), "--build", str(build_dir), "--out", str(out),
            "--runs", "2", "--seconds", str(title.boot_seconds), "--note", "title-runs", title.title_id]
    env = {"PATH": "/usr/bin:/bin"}
    for key in ("DISPLAY", "WAYLAND_DISPLAY", "XDG_RUNTIME_DIR", "XDG_SESSION_TYPE"):
        if os.environ.get(key):
            env[key] = os.environ[key]
    command = sandbox.command(config.sandbox, argv, out, read_only=[title.dump, build_dir, VENDOR, side_tree], writable=[out], env=env)
    with open(out / "title_run.log", "w") as stream:
        subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT, cwd=out, env=env if config.sandbox == "bwrap" else None)
    summaries = sorted(out.glob("*/summary.json"))
    log(f"title_run: {len(summaries)} summary in {out}")
    return json.loads(summaries[-1].read_text()) if summaries else None


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
                for key, label in (("A", "main"), ("B", "pr")):
                    summary = boot_and_classify(config, title, trees[key], builds[key]["dir"], job_dir / f"title_run-{label}", note)
                    entry.setdefault("boot", {})[key] = summary
                entry["outcome"] = {key: worst_outcome(entry["boot"].get(key), title_id) for key in ("A", "B")}
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


def worst_outcome(summary, title_id):
    if not summary:
        return "not run"
    runs = summary["titles"].get(title_id, {}).get("runs", [])
    return game.title_run.worst(runs) if runs else "not run"


def finish(job_dir, results):
    results["finished"] = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
    (job_dir / "results.json").write_text(json.dumps(results, indent=2, default=str))
    return results
