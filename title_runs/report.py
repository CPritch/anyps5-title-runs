"""The bot's comment for one PR, and the rule for posting a new comment instead of editing the existing one.

One comment per PR and machine, marked with an HTML comment so the poster finds it again. It shows the latest head in
full and the earlier heads in a history table. Edits do not notify anyone, so a new comment is posted when something a
developer should hear about happened: an outcome changed (a side that rendered now crashes, or the reverse), or the
frame-time verdict changed (no difference -> faster or slower, or faster <-> slower). Otherwise the comment is edited.
"""

import json
import statistics

MARK = "<!-- anyps5-title-runs machine={machine} -->"
TOOL = "anyps5-title-runs"


def mean(values):
    return statistics.mean(values) if values else None


def ms(values):
    return ", ".join(f"{v:.1f}" for v in values) + " ms" if values else "-"


def head_summary(results):
    """What the history table keeps of a head: outcome and verdict per title."""
    out = {"head": results["head"], "date": results.get("started", "")[:16].replace("T", " "), "status": results.get("status"),
           "base": results.get("base", ""), "titles": {}}
    for title_id, entry in results.get("titles", {}).items():
        v = entry.get("verdict") or {}
        sides = v.get("sides", {})
        out["titles"][title_id] = {"outcome": entry.get("outcome", {}), "verdict": v.get("verdict"), "diff": v.get("diff"),
                                   "diff_pct": v.get("diff_pct"), "p50_A": mean(sides.get("A", {}).get("p50", [])),
                                   "p50_B": mean(sides.get("B", {}).get("p50", []))}
    return out


def decide(previous, current, has_comment):
    """("new" | "edit", reason) for the current head's summary against the previous head's."""
    if not has_comment:
        return "new", "the first results for this PR on this machine"
    if previous is None:
        return "edit", "no earlier head to compare with"
    for title_id, now in current["titles"].items():
        before = previous["titles"].get(title_id)
        if before is None:
            return "new", f"{title_id}: a title with no earlier results"
        for side, name in (("A", "main"), ("B", "this PR")):
            old, new = before["outcome"].get(side), now["outcome"].get(side)
            if old and new and old.split(" ")[0] != new.split(" ")[0]:
                return "new", f"{title_id}: {name} went from {old.split(' ')[0]} to {new.split(' ')[0]}"
        old, new = before.get("verdict"), now.get("verdict")
        if new in ("faster", "slower") and old != new:
            return "new", f"{title_id}: the frame-time verdict went from {old or 'none'} to {new}"
    return "edit", "outcomes and verdicts are unchanged"


def machine_line(results):
    for entry in results.get("titles", {}).values():
        for run in entry.get("ab", {}).get("runs", []):
            s = run.get("summary")
            if s:
                return f"{s.get('gpu', '?')}, driver {s.get('driver', '?')}, {s.get('os', '?')}"
        for summary in (entry.get("boot") or {}).values():
            if summary:
                m = summary.get("machine", {})
                return f"{m.get('gpu', '?')}, driver {m.get('driver', '?')}, {m.get('os', '?')}"
    return "?"


def verdict_text(v):
    if v.get("diff") is None:
        return v.get("verdict", "no verdict")
    word = {"faster": "**faster**", "slower": "**slower**"}.get(v["verdict"], v["verdict"])
    return f"{word}: {v['diff']:+.2f} ms p50 ({v['diff_pct']:+.1f} %), spread {v['spread']:.2f} ms, GPU {v['gpu_diff']:+.2f} ms per present"


def render(config, number, results, history, notes=()):
    """The comment body: the latest head (results) and the earlier heads (history: head summaries, oldest first)."""
    head, merge, base = results["head"], results.get("merge", ""), results.get("base", "")
    sandbox = "bubblewrap (no network, no home directory, the dump read-only)" if results.get("sandbox") == "bwrap" else "**none** (the tester turned the sandbox off)"
    lines = [MARK.format(machine=config.machine), f"### Title runs on {config.tester or 'a tester'}'s {config.machine}", "",
             f"Automatic runs of this PR's heads on titles the tester owns. Each head is GitHub's merge of the PR "
             f"(`refs/pull/{number}/merge`), run against main at that merge's base, both built on this machine. "
             f"Numbers are from one machine and one scene; they are not a review.", ""]
    lines += [f"**Head `{head[:9]}`** (merged as `{merge[:9]}` on main `{base[:9]}`), {results.get('started', '')[:16].replace('T', ' ')}",
              f"Machine: {machine_line(results)}. Sandbox: {sandbox}.", ""]
    if results.get("simulated"):
        lines += [f"**Simulated head** (a fixture for the dry-run demonstration, not a run): {results['simulated']}", ""]
    if results.get("status") == "failed":
        lines += [f"The job failed: `{results.get('error', '?')}`", ""]
    if results.get("status") == "superseded":
        lines += [f"Not run: {results.get('detail', 'a newer head arrived')}.", ""]
    titles = results.get("titles", {})
    if titles:
        lines += ["| Title | Scene | main | this PR |", "|---|---|---|---|"]
        for title_id, entry in titles.items():
            name = f"{entry.get('name', title_id)} ({title_id} {entry.get('version', '')})".replace("|", "\\|")
            outcome = entry.get("outcome", {})
            lines.append(f"| {name} | {entry.get('scene', 'boot (no route)')} | {outcome.get('A', '-')} | {outcome.get('B', '-')} |")
        lines.append("")
    for title_id, entry in titles.items():
        v = entry.get("verdict")
        ab = entry.get("ab")
        if not ab or not v:
            continue
        sides = v.get("sides", {})
        graphics = config.titles[title_id].graphics_mode if title_id in config.titles else ""
        window = ab.get("window", {})
        lines += [f"**{title_id}**{', Graphics Mode ' + graphics if graphics else ''}: two counted runs per side in the order "
                  f"main, PR, main, PR; window `{window.get('spec', '?')}` (60 s, 30 s after the scene settles), caches warm, "
                  f"APS5_TRACE_EVENTS=4194304, no other trace or profile switch, the log on a pseudo-terminal.", ""]
        a, b = sides.get("A", {}), sides.get("B", {})
        lines += ["| | main | this PR |", "|---|---|---|"]
        for key, label in (("p50", "p50 frame"), ("p90", "p90"), ("p99", "p99"), ("gpu", "GPU per present")):
            lines.append(f"| {label} | {ms(a.get(key, []))} | {ms(b.get(key, []))} |")
        lines += ["", f"Verdict (a difference counts when it is larger than both sides' spreads): {verdict_text(v)}.", ""]
        not_counted = [r for r in ab.get("runs", []) if not r.get("counts")]
        if not_counted:
            lines += ["Runs that did not count: " + "; ".join(f"{r['run']}: {r.get('capture', '?').split('; ', 1)[-1]}" for r in not_counted), ""]
        counted = [r for r in ab.get("runs", []) if r.get("counts") and r.get("summary")]
        if counted:
            lines += ["<details><summary>Summary lines (main, then this PR; one per counted run)</summary>", "", "```"]
            lines += [json.dumps(r["summary"], separators=(",", ":")) for side in ("A", "B") for r in counted if r["side"] == side]
            lines += ["```", "", "</details>", ""]
        lines += [f"Screenshot: <!-- screenshot {title_id} {head[:9]}: last frame of the PR's run, attached by the poster when enabled --> not attached.", ""]
    for note in notes:
        lines += [note, ""]
    if history:
        lines += ["<details><summary>Earlier heads</summary>", "", "| Head | Date | Title | main | this PR | p50 main -> PR | Verdict |", "|---|---|---|---|---|---|---|"]
        for old in reversed(history):
            for title_id, t in old["titles"].items():
                change = f"{t['p50_A']:.1f} -> {t['p50_B']:.1f} ms ({t['diff']:+.2f})" if t.get("diff") is not None else "-"
                lines.append(f"| `{old['head'][:9]}` | {old['date']} | {title_id} | {t['outcome'].get('A', '-')} | {t['outcome'].get('B', '-')} | {change} | {t.get('verdict') or '-'} |")
            if not old["titles"]:
                lines.append(f"| `{old['head'][:9]}` | {old['date']} | - | - | - | - | {old.get('status')} |")
        lines += ["", "</details>", ""]
    lines += [f"<sub>{TOOL}: this comment is edited for each new head; a new comment is posted when an outcome or the verdict "
              f"changes. What leaves the tester's machine: timings, summary lines, outcome classes and, when enabled, a screenshot; "
              f"never game files.</sub>"]
    return "\n".join(lines) + "\n"
