#!/usr/bin/env python3
"""Timed captures in the Performance report form's protocol (APS5_TRACE_FRAMES window).

Usage:
  capture.py record <run>
      when the run reached the loaded Story (a diagnostic run whose meta has the loaded_at that
      nav.sh writes, or a timed run with its window summary line), appends it to story-loaded.tsv
      in the runs directory: started, machine, built commit, RUN_ENV, warm (a diagnostic run, which
      has a settle point) or timed, run. Once per run.
  capture.py warmed <runs-dir> <machine> <built-commit> [<run-env>]
      the latest run of that built commit and RUN_ENV on this machine that reached the loaded
      Story. Exits 1 when there is none: the caches are cold and a warm-up is needed.
  capture.py window <runs-dir> <machine> <built-commit> [<built-commit> ...] [--margin-s 30]
                    [--seconds 60] [--dump-every 30]
      one window for the builds to be compared, "<start>:<count> <dump-limit> <source-runs>", from
      the settle point (10 s summaries and loaded_at) of the latest warm run of each build, or of
      the latest warm run on this machine when a build has none. The window opens --margin-s
      seconds of steady presents after the latest of those settle points and holds --seconds of
      steady presents (60 s: with APS5_TRACE_EVENTS=4194304 the queue-0 worker's buffer holds about
      90 s on the laptop, 16 times the 5.7 s the default held on 2026-10-19). Frame dumps stop half a
      margin before the window opens.
  capture.py check <run> [--dump-every 30]
      the timed run's window summary line: one line, complete totals (no thread's totals table
      full; a thread that only lost trace events still has complete totals, BUILD.md), no load
      frame in the window (max under 5 times p50), no pipeline build in the window (see
      pipeline_builds), frame dumps stopped before the window opened.
      Prints one "capture:" line, which names the threads whose trace stops early, and exits 1
      when the run does not count.
  capture.py row <run> <note>
      the draft ledger row of a timed run (base, title, graphics mode, machine, postable).
  capture.py quiet <run> --since <seconds> [--seconds 60]
      whether a diagnostic run still builds pipelines. Quiet means: its 10 s summaries cover at least
      --seconds after --since (the loaded_at nav.sh records), no summary ending in the last --seconds
      lists a Vulkan.GraphicsPipeline* phase among its top phases, and the pipeline cache file in the
      run's shader cache version directory was not written in the last --seconds. The summaries list
      only the 8 largest phases, which a pipeline phase leaves below about 20 ms per frame; the driver
      saves the cache file every 10 s when it holds new pipelines and no creation holds the lock, so
      light building rewrites the file and only heavy building, which the phases show, keeps it from
      being saved. Prints one "quiet:" line; exits 0 when quiet.
  capture.py report <ab-dir>
      ab.md for an A/B made by ab.sh: the summary lines, the spread of each side, the difference,
      tools/performance_compare.py for each pair, and draft ledger rows.
"""
import argparse
import gzip
import json
import pathlib
import re
import statistics
import subprocess
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent.parent


def meta(run):
    out = {}
    for line in (pathlib.Path(run) / "meta").read_text().splitlines():
        key, _, value = line.partition("=")
        out.setdefault(key, value)
    return out


def intervals(path):
    rows = []
    for line in open(path):
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if "interval_start_s" in row and row.get("frame_ms"):
            rows.append(row)
    return rows


def window_line(run):
    lines = []
    path = pathlib.Path(run) / "aps5-summary.jsonl"
    if path.exists():
        for line in path.read_text().splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if row.get("trace"):
                lines.append(row)
    return lines


def calibrate(run):
    m = meta(run)
    found = re.search(r"loaded_at=([\d.]+)", m.get("window", "") + " " + " ".join(f"{k}={v}" for k, v in m.items()))
    if not found:
        raise SystemExit(f"{run}: no loaded_at in meta (did its warm-up reach the loaded Story?)")
    loaded = float(found.group(1))
    rows = intervals(pathlib.Path(run) / "aps5-summary.jsonl")
    at = [r for r in rows if r["interval_start_s"] <= loaded + 0.5 <= r["interval_end_s"] + 0.5]
    steady = [r for r in rows if r["interval_start_s"] >= loaded - 0.5]
    if not at or not steady:
        raise SystemExit(f"{run}: no summary interval at or after loaded_at {loaded}")
    rate = sum(r["presents"] for r in steady) / (sum(r["window"]["ms"] for r in steady) / 1000)
    return at[0]["window"]["first_present"], rate


INDEX = "story-loaded.tsv"
COLUMNS = ("started", "machine", "built_from", "run_env", "kind", "run")


def run_env_key(value):
    return " ".join(sorted(value.split())) if value and value != "(none)" else ""


def same_commit(a, b):
    return bool(a) and bool(b) and (a.startswith(b) or b.startswith(a))


def loaded_runs(runs_dir, machine):
    path = pathlib.Path(runs_dir) / INDEX
    rows = []
    if path.exists():
        for line in path.read_text().splitlines():
            if line and not line.startswith("#"):
                rows.append(dict(zip(COLUMNS, line.split("\t"))))
    return sorted((r for r in rows if machine is None or r["machine"] == machine), key=lambda r: r["started"])


def record(args):
    run = pathlib.Path(args.run).resolve()
    m = meta(run)
    if m.get("capture", "diagnostic").startswith("timed"):
        kind, reached = "timed", len(window_line(run)) == 1
    else:
        kind, reached = "warm", "loaded_at" in m
    if not reached:
        print(f"{run.name}: did not reach the loaded Story; not recorded")
        return 1
    if any(r["run"] == run.name for r in loaded_runs(run.parent, None)):
        return 0
    path = run.parent / INDEX
    fields = (m.get("started", ""), m.get("machine", "?"), m.get("built_from", "?"),
              run_env_key(m.get("run_env", "")) or "(none)", kind, run.name)
    with open(path, "a") as out:
        if out.tell() == 0:
            out.write("# " + "\t".join(COLUMNS) + "\n")
        out.write("\t".join(fields) + "\n")
    print(f"{run.name}: reached the loaded Story ({kind}, built {fields[2][:9]}, RUN_ENV {fields[3]}); recorded in {path}")
    return 0


def warmed(args):
    key = run_env_key(args.run_env)
    hits = [r for r in loaded_runs(args.runs_dir, args.machine)
            if same_commit(r["built_from"], args.built) and run_env_key(r["run_env"]) == key]
    if not hits:
        print(f"cold: no run of {args.built[:9]} with RUN_ENV {key or '(none)'} has reached the loaded Story on {args.machine}")
        return 1
    print(hits[-1]["run"])
    return 0


def window(args):
    warm = [r for r in loaded_runs(args.runs_dir, args.machine) if r["kind"] == "warm"]
    if not warm:
        raise SystemExit(f"no warm run on {args.machine} in {pathlib.Path(args.runs_dir) / INDEX} to take a window from")
    marks = {}
    for built in args.builds:
        own = [r for r in warm if same_commit(r["built_from"], built)]
        candidates = [(r, "this build") for r in reversed(own)]
        candidates += [(r, "latest on this machine; the build has none" if not own else "latest on this machine")
                       for r in reversed(warm) if r not in own]
        for r, why in candidates:
            try:
                marks.setdefault(r["run"], (calibrate(pathlib.Path(args.runs_dir) / r["run"]), built, why))
                break
            except SystemExit as error:
                print(f"  skipped {r['run']}: {error}", file=sys.stderr)
        else:
            raise SystemExit(f"no warm run on {args.machine} gives a settle point for {built[:9]}")
    start_present = max(p for (p, _), _, _ in marks.values())
    rate = min(r for (_, r), _, _ in marks.values())
    margin = int(args.margin_s * rate)
    start = (start_present + margin + 99) // 100 * 100
    count = max(100, int(args.seconds * rate) // 100 * 100)
    dump_limit = max(1, (start - margin // 2) // args.dump_every)
    print(f"{start}:{count} {dump_limit} {','.join(marks)}")
    for run, ((p, r), built, why) in marks.items():
        print(f"  {run} (for {built[:9]}, {why}): settled at present {p}, {r:.1f} presents/s", file=sys.stderr)


# Pipeline creation scopes (Graphics/src/PipelineLibrary.cpp, Graphics/src/Pipeline.cpp,
# Execution/src/VulkanDevice.cpp). A library slice opens only after the in-memory library cache
# missed; Vulkan.GraphicsPipeline (the Pipeline constructor) holds the library slices it creates.
CREATIONS = ("Vulkan.GraphicsPipelineLibrary", "Vulkan.GraphicsPipelineLink", "Vulkan.ComputePipeline")
BUILD_MS = 20.0


def pipeline_builds(run, s):
    """Pipeline builds in the window: creation slices of BUILD_MS or more, read from the trace.

    The trace is the reliable source: it holds every slice of 20 us or more of every traced thread
    until that thread's buffer fills (trace_dropped_threads says when), while the summary line lists
    only its eight largest phases, so a pipeline phase missing from it proves nothing. BUILD_MS
    separates compiles from creations the driver serves from its pipeline cache: on 2026-10-19 the
    window's 274 library creations took either under 10 ms (77) or over 50 ms (197), none in between.
    A Vulkan.GraphicsPipeline slice counts on its own only when it holds no counted creation (a
    pipeline made without libraries). Returns None when the run has no trace."""
    path = pathlib.Path(run) / s.get("trace", "")
    if not s.get("trace") or not path.exists():
        return None
    names, leaves, whole = {}, [], []
    with gzip.open(path, "rt") as trace:
        for line in trace:
            if '"thread_name"' not in line and "Pipeline" not in line:
                continue
            try:
                event = json.loads(line.strip().rstrip(","))
            except ValueError:
                continue
            if event.get("ph") == "M" and event.get("name") == "thread_name":
                names[event["tid"]] = event["args"]["name"]
            elif event.get("ph") == "X" and event.get("dur", 0) >= BUILD_MS * 1000:
                if event["name"] in CREATIONS:
                    leaves.append(event)
                elif event["name"] == "Vulkan.GraphicsPipeline":
                    whole.append(event)
    builds = leaves + [w for w in whole if not any(l["tid"] == w["tid"] and w["ts"] <= l["ts"] <= w["ts"] + w["dur"] for l in leaves)]
    return [(e["name"], names.get(e["tid"], str(e["tid"])), e["dur"] / 1000) for e in builds]


def check(args):
    run = pathlib.Path(args.run)
    m = meta(run)
    lines = window_line(run)
    reasons = []
    if len(lines) != 1:
        print(f"capture: not counted: {len(lines)} window summary lines in {run.name}")
        return 1
    s = lines[0]
    f = s["frame_ms"]
    dropped = s.get("trace_dropped_threads", {})
    full = sorted(name for name, v in dropped.items() if v.get("totals_full"))
    if full:
        reasons.append(f"totals table full for {', '.join(full)} (the summary is incomplete)")
    if f["max"] >= 5 * f["p50"]:
        reasons.append(f"a {f['max']:.0f} ms frame in the window (load or stall)")
    builds = pipeline_builds(run, s)
    if builds is None:
        reasons.append("no trace to check for pipeline builds")
    elif builds:
        threads = sorted({t for _, t, _ in builds})
        reasons.append(f"{len(builds)} pipeline builds of {BUILD_MS:.0f} ms or more in the window "
                       f"({sum(d for _, _, d in builds) / 1000:.1f} s on {', '.join(threads)})")
    limit = re.search(r"dump_limit=(\d+)", m.get("capture", ""))
    if limit and int(limit.group(1)) * args.dump_every >= s["window"]["first_present"]:
        reasons.append("frame dumps may have reached the window")
    if s.get("dirty") is not False:
        reasons.append("the build's tree was dirty")
    verdict = "counts" if not reasons else "not counted: " + "; ".join(reasons)
    print(f"capture: {s['window']['spec']}, {s['presents']} presents, p50 {f['p50']:.1f} ms, p90 {f['p90']:.1f}, "
          f"p99 {f['p99']:.1f}, max {f['max']:.1f}, GPU {s['gpu_busy_ms_per_present']:.1f} ms/present, commit {s['commit']}; {verdict}"
          f"{'; no pipeline builds' if builds == [] else ''}"
          f"{'; ' + incomplete_trace(s) if incomplete_trace(s) else ''}")
    return 0 if not reasons else 1


def incomplete_trace(s):
    """Threads whose trace events stopped before the window closed (their digest rows cover less)."""
    lost = [f"{name} after {v['events_full_after_s']:.1f} s" if "events_full_after_s" in v else name
            for name, v in sorted(s.get("trace_dropped_threads", {}).items()) if v.get("events_lost") or name == "gpu"]
    return f"trace incomplete: {', '.join(lost)} of {s['window']['ms'] / 1000:.0f} s" if lost else ""


def row(args):
    run = pathlib.Path(args.run)
    lines = window_line(run)
    if len(lines) != 1:
        raise SystemExit(f"{run.name}: {len(lines)} window summary lines")
    print(ledger_row(run, lines[0], args.note))


PIPELINE_PHASE = "Vulkan.GraphicsPipeline"


def pipeline_cache_file(run):
    log = pathlib.Path(run) / "game.log"
    if not log.exists():
        return None
    for line in log.read_text(errors="replace").splitlines():
        m = re.match(r"\[shader-disk-cache\] (/.*?) \(source version", line)
        if m:
            files = sorted(pathlib.Path(m.group(1)).glob("vk-pipelines-*.bin"), key=lambda f: f.stat().st_mtime)
            return files[-1] if files else pathlib.Path(m.group(1)) / "vk-pipelines-*.bin"
    return None


def quiet(args):
    rows = [r for r in intervals(pathlib.Path(args.run) / "aps5-summary.jsonl") if r["interval_end_s"] > args.since]
    last = rows[-1]["interval_end_s"] if rows else args.since
    if last - args.since < args.seconds:
        print(f"quiet: not yet ({last - args.since:.0f} s of summaries after the Story loaded)")
        return 1
    recent = [r for r in rows if r["interval_end_s"] > last - args.seconds + 1]
    building = [(r["interval_end_s"], max([v for k, v in (r.get("top_phases_ms_per_frame") or {}).items() if k.startswith(PIPELINE_PHASE)], default=0)) for r in recent]
    building = [(end, ms) for end, ms in building if ms > 0]
    if building:
        print(f"quiet: no, pipeline phases in {len(building)} of the last {len(recent)} summaries (up to {max(ms for _, ms in building):.0f} ms per frame, at {last:.0f} s)")
        return 1
    cache = pipeline_cache_file(args.run)
    if cache is not None and cache.exists():
        age = time.time() - cache.stat().st_mtime
        if age < args.seconds:
            print(f"quiet: no, {cache.name} written {age:.0f} s ago (at {last:.0f} s)")
            return 1
        written = f"{cache.name} last written {age:.0f} s ago"
    else:
        written = "no pipeline cache file yet"
    print(f"quiet: yes, no pipeline phase in the last {len(recent)} summaries and {written} (at {last:.0f} s)")
    return 0


def spread(values):
    return max(values) - min(values) if len(values) > 1 else float("nan")


def dump_note(s):
    """Frame dumps in a timed run are accepted when they stop before the window; every row says where."""
    limit, every = s["env"].get("APS5_DUMP_FRAMES"), s["env"].get("APS5_DUMP_FRAMES_EVERY", "30")
    if not limit:
        return "no frame dumps"
    return f"frame dumps in boot and load to present {int(limit) * int(every)} (APS5_DUMP_FRAMES={limit}, every {every} presents)"


def ledger_row(run, s, note):
    m = meta(run)
    base = m.get("base", "?")
    # Postable rows need glibc's allocator; tcmalloc stays for our own builds, whose rows are not postable.
    allocator = m.get("allocator", "glibc").split(" ")[0]
    public = "public_only=yes" in m.get("base_source_commit", "")
    graphics = m.get("graphics", "unknown")
    terminal = m.get("log", "").startswith("terminal")  # a pseudo-terminal from script(1) counts
    postable = public and allocator == "glibc" and terminal and not graphics.startswith("unknown")
    why = [] if postable else [w for w, bad in (("local changes", not public), (f"allocator {allocator}", allocator != "glibc"),
                                                ("log not on a terminal", not terminal), ("graphics mode unknown", graphics.startswith("unknown"))) if bad]
    switches = " ".join(sorted(k for k in s["env"] if k not in ("APS5_TRACE_FRAMES", "APS5_TRACE_EVENTS", "APS5_PAD_INPUT_FILE", "APS5_NO_PAD_INPUT", "APS5_DUMP_FRAMES", "APS5_DUMP_FRAMES_EVERY")))
    events = f", APS5_TRACE_EVENTS={s['env']['APS5_TRACE_EVENTS']}" if "APS5_TRACE_EVENTS" in s["env"] else ""
    f = s["frame_ms"]
    return (f"| {m.get('started', '')[:10]} | {m.get('machine', '?')} ({s['gpu']}, {s['driver']}) | {base} | {m.get('title', '?')} | {graphics} "
            f"| timed, APS5_TRACE_FRAMES={s['env'].get('APS5_TRACE_FRAMES', '?')}{events}, {dump_note(s)}, {allocator}{', ' + switches if switches else ''} | bench | "
            f"{note}: p50 {f['p50']:.1f} ms, p90 {f['p90']:.1f}, p99 {f['p99']:.1f}, GPU {s['gpu_busy_ms_per_present']:.1f} ms/present, "
            f"commit {s['commit']}{'; ' + incomplete_trace(s) if incomplete_trace(s) else ''} | {'yes' if postable else 'no (' + ', '.join(why) + ')'} |")


def prs_of(run):
    return {n: h for n, h, _ in re.findall(r"#(\d+)@([0-9a-f]+)\((\w+)\)", meta(run).get("base", ""))}


def pr_comment(runs, summaries):
    """When B is A plus one public PR, both on plain main: the comment #5503 asks for (head commit,
    device, driver, difference from main on the same machine), with the summary lines."""
    if not all(len(runs[side]) >= 2 for side in runs):
        return None
    a, b = runs["A"][0], runs["B"][0]
    ma, mb = meta(a), meta(b)
    extra = {n: h for n, h in prs_of(b).items() if n not in prs_of(a)}
    public = all("public_only=yes" in m.get("base_source_commit", "") for m in (ma, mb))
    if len(extra) != 1 or not public or set(prs_of(a)) - set(prs_of(b)):
        return None
    (number, head), = extra.items()
    sa, sb = summaries["A"], summaries["B"]
    p50a = [x["frame_ms"]["p50"] for x in sa]
    p50b = [x["frame_ms"]["p50"] for x in sb]
    gpua = statistics.mean(x["gpu_busy_ms_per_present"] for x in sa)
    gpub = statistics.mean(x["gpu_busy_ms_per_present"] for x in sb)
    diff = statistics.mean(p50b) - statistics.mean(p50a)
    base = re.search(r"main ([0-9a-f]+)", ma.get("base", "")).group(1)
    lines = [
        f"Ran this on GTA V ({ma.get('title', '?')}), {sa[0]['os']}, {sa[0]['gpu']}, {sa[0]['driver']}, Graphics Mode {ma.get('graphics', '?')}, "
        f"the Story prologue after Resume Story, with no input.",
        f"main {base} against main {base} + #{number} at {head}, same machine and session, two runs each in the order A B A B, "
        f"window {sa[0]['window']['spec']}, caches warm, APS5_TRACE_EVENTS={sa[0]['env'].get('APS5_TRACE_EVENTS', 'unset')} (BUILD.md's remedy for "
        f"full trace buffers), no other APS5_TRACE_* or APS5_PROFILE_* switch, log not redirected. "
        f"The harness navigates the menus from {dump_note(sa[0])}, which stop before the window.",
        f"Frame p50: main {', '.join(f'{v:.1f}' for v in p50a)} ms, with #{number} {', '.join(f'{v:.1f}' for v in p50b)} ms "
        f"({diff:+.1f} ms, {diff / statistics.mean(p50a) * 100:+.1f} %). GPU busy per present: {gpua:.1f} and {gpub:.1f} ms.",
        "Not tested: other scenes, Fidelity mode, other GPUs.",
        "",
        "Summary lines (main, then the PR):",
    ] + [json.dumps(x, separators=(",", ":")) for x in sa[:1] + sb[:1]]
    return "\n".join(lines)


def report(args):
    ab = pathlib.Path(args.dir)
    runs = {"A": [], "B": []}
    for line in (ab / "runs").read_text().splitlines():
        side, run, verdict = line.split("\t")
        if verdict == "counts":
            runs[side].append(pathlib.Path(run))
    summaries = {side: [window_line(r)[0] for r in rs] for side, rs in runs.items()}
    out = [f"# A/B {ab.name}", "", (ab / "plan").read_text().strip(), ""]
    out += ["| side | run | p50 ms | p90 ms | p99 ms | max ms | GPU ms/present | presents | commit |", "|---|---|---|---|---|---|---|---|---|"]
    for side in ("A", "B"):
        for run, s in zip(runs[side], summaries[side]):
            f = s["frame_ms"]
            out.append(f"| {side} | {run.name} | {f['p50']:.1f} | {f['p90']:.1f} | {f['p99']:.1f} | {f['max']:.1f} | {s['gpu_busy_ms_per_present']:.1f} | {s['presents']} | {s['commit']} |")
    out.append("")
    if all(len(runs[side]) >= 2 for side in runs):
        p50 = {side: [s["frame_ms"]["p50"] for s in summaries[side]] for side in summaries}
        gpu = {side: [s["gpu_busy_ms_per_present"] for s in summaries[side]] for side in summaries}
        diff = statistics.mean(p50["B"]) - statistics.mean(p50["A"])
        limit = max(spread(p50["A"]), spread(p50["B"]))
        out.append(f"p50: A {', '.join(f'{v:.1f}' for v in p50['A'])} (spread {spread(p50['A']):.1f}); "
                   f"B {', '.join(f'{v:.1f}' for v in p50['B'])} (spread {spread(p50['B']):.1f}); "
                   f"B - A = {diff:+.2f} ms ({diff / statistics.mean(p50['A']) * 100:+.1f} %); "
                   f"GPU B - A = {statistics.mean(gpu['B']) - statistics.mean(gpu['A']):+.2f} ms.")
        out.append(f"Verdict by the rule (a difference counts when it is larger than both sides' spreads): "
                   f"{'B differs from A' if abs(diff) > limit else 'no difference beyond the spread'}.")
    else:
        out.append(f"Not enough counted runs for a verdict: A {len(runs['A'])}, B {len(runs['B'])} (two per side needed).")
    compare = subprocess.run(["python3", str(HERE / "upstream-status.py"), "tool", "performance_compare.py"],
                             capture_output=True, text=True, check=True).stdout.strip()
    for i, (a, b) in enumerate(zip(runs["A"], runs["B"]), 1):
        result = subprocess.run(["python3", "-I", str(compare), str(a / "aps5-summary.jsonl"), str(b / "aps5-summary.jsonl")],
                                capture_output=True, text=True)
        text = result.stdout if result.returncode == 0 else result.stderr
        out += ["", f"## tools/performance_compare.py, pair {i}: {a.name} against {b.name}", "", text.replace("# Performance comparison", "").strip()]
    draft = pr_comment(runs, summaries)
    if draft:
        out += ["", "## Draft comment for the PR (for Charlie; nothing is posted)", "", "```", draft, "```"]
    out += ["", "## Draft ledger rows", ""]
    for side in ("A", "B"):
        for run, s in zip(runs[side], summaries[side]):
            out.append(ledger_row(run, s, f"A/B {ab.name} side {side}"))
    (ab / "ab.md").write_text("\n".join(out) + "\n")
    print("\n".join(out))


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("record")
    p.add_argument("run")
    p = sub.add_parser("warmed")
    p.add_argument("runs_dir")
    p.add_argument("machine")
    p.add_argument("built")
    p.add_argument("run_env", nargs="?", default="")
    p = sub.add_parser("window")
    p.add_argument("runs_dir")
    p.add_argument("machine")
    p.add_argument("builds", nargs="+")
    p.add_argument("--margin-s", type=float, default=30)
    p.add_argument("--seconds", type=float, default=60)
    p.add_argument("--dump-every", type=int, default=30)
    p = sub.add_parser("check")
    p.add_argument("run")
    p.add_argument("--dump-every", type=int, default=30)
    p = sub.add_parser("row")
    p.add_argument("run")
    p.add_argument("note")
    p = sub.add_parser("report")
    p.add_argument("dir")
    p = sub.add_parser("quiet")
    p.add_argument("run")
    p.add_argument("--since", type=float, required=True)
    p.add_argument("--seconds", type=float, default=60)
    args = parser.parse_args()
    return {"record": record, "warmed": warmed, "window": window, "check": check, "row": row, "report": report, "quiet": quiet}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
