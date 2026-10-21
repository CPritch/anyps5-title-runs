"""The App's comment on a PR: the approved head's results from every machine, what is still wanted, pushes after the
approval, runs on testers' own trust, and earlier heads. Rendered from queue.json and results/ only.

Every value shown comes from a result that formats.check_result has accepted (no markup characters in text, numbers
as numbers, summary lines as single lines), and the summary lines go into code blocks.
"""

import datetime
import statistics

from .. import formats

MARK = "<!-- anyps5-title-runs pr={pr} -->"


def short(sha):
    return sha[:9]


def utc(stamp):
    try:
        return formats.parse_time(stamp).astimezone(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    except formats.FormatError:
        return "?"


def mean(values):
    return statistics.mean(values) if values else None


def outcome_class(text):
    return (text or "").split(" ")[0]


def title_name(title_id, entry):
    name = entry.get("name") or title_id
    return f"{name} ({title_id})"


def p50_change(entry):
    sides = entry.get("sides") or {}
    a, b = mean(sides.get("A", {}).get("p50", [])), mean(sides.get("B", {}).get("p50", []))
    return f"{a:.1f} → {b:.1f} ms" if a is not None and b is not None else ""


def verdict_word(entry):
    v = entry.get("verdict") or {}
    word = v.get("verdict", "")
    return {"faster": "**faster**", "slower": "**slower**"}.get(word, word)


def rows(results):
    """One table row per machine and title of the given results ({machine: result})."""
    out = []
    for machine, result in sorted(results.items()):
        if result["status"] != "done":
            out.append(f"| {machine} | {result['machine_line']} | | {result['status']}{': ' + result['error'] if result.get('error') else ''} | | |")
            continue
        for title_id, entry in sorted(result["titles"].items()):
            outcome = entry["outcome"]
            out.append(f"| {machine} | {result['machine_line']} | {title_name(title_id, entry)} | {outcome['A']} / {outcome['B']} | "
                       f"{p50_change(entry)} | {verdict_word(entry)} |")
    return out


def still_wanted(entry, results):
    reported = [m for m, r in results.items() if r["status"] == "done"]
    missing = entry["machines"] - len(reported)
    if missing <= 0:
        return None
    hw = ", ".join(entry["hw"]) if entry["hw"] else "any hardware"
    titles = ", ".join(entry["titles"]) if entry["titles"] else "any"
    return f"| still wanted | {missing} more machine{'s' if missing > 1 else ''}: {hw} | {titles} | | | |"


def details(results):
    lines = []
    for machine, result in sorted(results.items()):
        if result["status"] != "done":
            continue
        for title_id, entry in sorted(result["titles"].items()):
            sides = entry.get("sides") or {}
            lines += [f"**{machine}, {title_id}**: main `{short(result.get('base', ''))}` (A) against `{short(result['head'])}` merged onto it "
                      f"(B), {entry.get('scene', '')}; sandbox {'bubblewrap' if result['sandbox'] == 'bwrap' else '**off**'}.", "",
                      "| | main | this PR |", "|---|---|---|"]
            for key, label in (("p50", "p50 frame"), ("p90", "p90"), ("p99", "p99"), ("gpu", "GPU per present")):
                a = ", ".join(f"{v:.1f}" for v in sides.get("A", {}).get(key, [])) or "-"
                b = ", ".join(f"{v:.1f}" for v in sides.get("B", {}).get(key, [])) or "-"
                lines.append(f"| {label} | {a} ms | {b} ms |")
            v = entry.get("verdict") or {}
            if v.get("diff") is not None:
                lines += ["", f"p50 {v['diff']:+.2f} ms ({v['diff_pct']:+.1f} %), spread {v['spread']:.2f} ms, GPU {v['gpu_diff']:+.2f} ms per "
                              f"present. A difference counts when it is larger than both sides' spreads."]
            summary = entry.get("summary_lines") or {}
            if summary:
                lines += ["", "```"] + [line for side in ("A", "B") for line in summary.get(side, [])] + ["```"]
            lines.append("")
    return lines


def render(pr, entry, by_head, tester_results=None, stopped=None):
    """by_head: {head sha: {machine: result}} for the queue's approved heads (the current one and earlier ones);
    tester_results: {head: {machine: result}} run on a tester's own trust. entry: the queue entry, or None when the PR
    is off the queue (stopped: who took it off)."""
    lines = [MARK.format(pr=pr)]
    current = entry["head"] if entry else None
    if entry:
        approval = entry["approval"]
        how = {"label": "label", "command": "command", "carried": "carried over"}[approval["via"]]
        lines += [f"### Title runs for `{short(current)}` (queued by @{entry['queued_by']}, {entry['priority']})", "",
                  f"Queued `{short(current)}` for title runs: approved by @{approval['by']} ({how}, {utc(approval['at'])})."
                  + (f" Carried over from `{short(approval['from'])}`: {approval['reason']}." if approval["via"] == "carried" else ""),
                  "Each machine fetches this commit, merges it onto main locally and runs it against that main, both built on the "
                  "machine in a sandbox. Numbers are from one machine and one scene each; they are not a review.", ""]
        for push in entry.get("unapproved", []):
            lines.append(f"`{short(push['sha'])}` pushed after approval by @{push['by']}: **not checked**. Testers keep to "
                         f"`{short(current)}` until a maintainer approves a newer head.")
        if entry.get("unapproved"):
            lines.append("")
    else:
        lines += [f"### Title runs", "", f"Off the queue{f' (stopped by @{stopped})' if stopped else ''}.", ""]
    results = by_head.get(current, {}) if current else {}
    header = ["| machine | GPU, driver, OS | title | outcome main / PR | p50 main → PR | verdict |", "|---|---|---|---|---|---|"]
    table = rows(results)
    wanted = still_wanted(entry, results) if entry else None
    if table or wanted:
        lines += header + table + ([wanted] if wanted else []) + [""]
    detail = details(results)
    if detail:
        lines += ["<details><summary>Per machine: the timed runs and summary lines</summary>", ""] + detail + ["</details>", ""]
    for head, trusted in sorted((tester_results or {}).items()):
        if trusted:
            lines += [f"**Run on the tester's trust** (`{short(head)}`, not approved by a maintainer):", ""] + header + rows(trusted) + [""]
    earlier = [h for h in (entry.get("earlier", []) if entry else by_head) if h != current and by_head.get(h)]
    if earlier:
        lines += ["<details><summary>Earlier heads</summary>", ""] + header
        for head in reversed(earlier):
            lines += [row.replace("| ", f"| `{short(head)}` ", 1) for row in rows(by_head[head])]
        lines += ["", "</details>", ""]
    lines.append("<sub>anyps5-title-runs: this comment is edited as machines report; a new comment is posted when an outcome "
                 "or a verdict changes. What leaves a tester's machine: timings, summary lines and outcome classes; never game "
                 "files.</sub>")
    return "\n".join(lines) + "\n"


def snapshot(by_head, tester_results=None):
    """What a post showed: {head: {machine: {title: [outcome A class, outcome B class, verdict]}}}."""
    out = {}
    for group in (by_head, tester_results or {}):
        for head, results in group.items():
            for machine, result in results.items():
                if result["status"] != "done":
                    continue
                for title_id, entry in result["titles"].items():
                    out.setdefault(head, {}).setdefault(machine, {})[title_id] = [
                        outcome_class(entry["outcome"]["A"]), outcome_class(entry["outcome"]["B"]), (entry.get("verdict") or {}).get("verdict")]
    return out


def latest(shot, order):
    """{(machine, title): state} of the latest head (in order) each machine and title reported."""
    out = {}
    for head in order:
        for machine, titles in shot.get(head, {}).items():
            for title_id, state in titles.items():
                out[(machine, title_id)] = state
    return out


def decide(previous, current, order):
    """("new" | "edit", reason): new when, for a machine and title, an outcome class changed or the verdict changed to
    faster or slower since the previous post."""
    if previous is None:
        return "new", "the first comment on this PR"
    before, now = latest(previous, order), latest(current, order)
    for key, state in sorted(now.items()):
        old = before.get(key)
        if old is None:
            continue
        machine, title_id = key
        for i, side in ((0, "main"), (1, "this PR")):
            if old[i] != state[i]:
                return "new", f"{machine}, {title_id}: {side} went from {old[i]} to {state[i]}"
        if state[2] in ("faster", "slower") and old[2] != state[2]:
            return "new", f"{machine}, {title_id}: the verdict went from {old[2]} to {state[2]}"
    return "edit", "no outcome or verdict changed"
