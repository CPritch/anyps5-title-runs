"""The App's comment on a PR: what the queue holds for it, the approved head's results from every machine, the combined
verdict per class of machines, what is still wanted, runs on testers' own trust, earlier heads, and what happened to the
approval (a push expired it, or a label came after the head). Rendered from the state files only.

Every value shown comes from a result that formats.check_result accepted (no markup characters in text, numbers as
numbers, summary lines as single lines); verdicts are recomputed from the p50 lists (verdict.py); summary lines go
into code blocks.
"""

import datetime

from .. import formats, verdict

MARK = "<!-- anyps5-title-runs pr={pr} -->"


def short(sha):
    return (sha or "")[:9]


def utc(stamp):
    try:
        return formats.parse_time(stamp).astimezone(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    except formats.FormatError:
        return "?"


def outcome_class(text):
    return (text or "").split(" ")[0]


def title_name(title_id, entry):
    return f"{entry.get('name') or title_id} ({title_id})"


def machine_verdict(entry):
    return verdict.machine(entry.get("sides") or {})


def p50_change(entry):
    v = machine_verdict(entry)
    sides = entry.get("sides") or {}
    a, b = sides.get("A", {}).get("p50", []), sides.get("B", {}).get("p50", [])
    if v.get("diff") is None or not a or not b:
        return ""
    return f"{sum(a) / len(a):.1f} → {sum(b) / len(b):.1f} ms"


def verdict_word(entry):
    v = machine_verdict(entry)
    word = {"faster": "**faster**", "slower": "**slower**"}.get(v["verdict"], v["verdict"])
    return word + (" (borderline)" if v.get("borderline") else "")


HEADER = ["| machine | GPU, driver, OS | title | outcome main / PR | p50 main → PR | verdict |", "|---|---|---|---|---|---|"]


def rows(results, prefix=""):
    out = []
    for name, result in sorted(results.items()):
        if result["status"] != "done":
            out.append(f"| {prefix}{name} | {result['machine_line']} | | {result['status']}{': ' + result['error'] if result.get('error') else ''} | | |")
            continue
        for title_id, entry in sorted(result["titles"].items()):
            outcome = entry["outcome"]
            out.append(f"| {prefix}{name} | {result['machine_line']} | {title_name(title_id, entry)} | {outcome['A']} / {outcome['B']} | "
                       f"{p50_change(entry)} | {verdict_word(entry)} |")
    return out


def combined_lines(results):
    lines = []
    titles = sorted({t for r in results.values() if r["status"] == "done" for t in r["titles"]})
    for title_id in titles:
        for combined in verdict.by_class(results, title_id).values():
            text = combined["text"]
            for word in ("Faster", "Slower", "Mixed"):
                if text.startswith(word):
                    text = f"**{word}**" + text[len(word):]
            lines.append(f"- {title_id}: {text}.")
    return lines


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
    for name, result in sorted(results.items()):
        if result["status"] != "done":
            continue
        for title_id, entry in sorted(result["titles"].items()):
            sides = entry.get("sides") or {}
            lines += [f"**{name}, {title_id}**: main `{short(result.get('base', ''))}` (A) against `{short(result['head'])}` merged onto it "
                      f"(B), {entry.get('scene', '')}; sandbox {'bubblewrap' if result['sandbox'] == 'bwrap' else '**off**'}.", "",
                      "| | main | this PR |", "|---|---|---|"]
            for key, label in (("p50", "p50 frame"), ("p90", "p90"), ("p99", "p99"), ("gpu", "GPU per present")):
                a = ", ".join(f"{v:.1f}" for v in sides.get("A", {}).get(key, [])) or "-"
                b = ", ".join(f"{v:.1f}" for v in sides.get("B", {}).get(key, [])) or "-"
                lines.append(f"| {label} | {a} ms | {b} ms |")
            v = machine_verdict(entry)
            if v.get("diff") is not None:
                gpu = f", GPU {v['gpu_diff']:+.2f} ms per present" if v.get("gpu_diff") is not None else ""
                lines += ["", f"p50 {v['diff']:+.2f} ms ({v['diff_pct']:+.1f} %); spread {v['spread']:.2f} ms; 1 % of main {v['size']:.2f} ms{gpu}. "
                              f"A difference counts when it is larger than both."]
            summary = entry.get("summary_lines") or {}
            if summary:
                lines += ["", "```"] + [line for side in ("A", "B") for line in summary.get(side, [])] + ["```"]
            lines.append("")
    return lines


def notices(pr, expired, refused, label):
    lines = []
    for item in expired:
        lines.append(f"**Approval of `{short(item['head'])}` expired**: `{short(item['by'])}` was pushed after it"
                     f"{' by @' + item['pusher'] if item.get('pusher') else ''} ({utc(item['at'])}) and is not checked. "
                     f"The App removed `{label}`; add it again to queue `{short(item['by'])}`.")
    for item in refused:
        lines.append(f"`{label}` added by @{item['by']} ({utc(item['labelled'])}) was not queued: the head `{short(item['head'])}` was pushed "
                     f"after it ({utc(item['pushed'])}). Add the label again, or comment `/title-test sha=<the commit you checked>`.")
    return lines


def render(pr, entry, by_head, tester_results=None, stopped=None, expired=(), refused=(), label="title-test"):
    """by_head: {head: {machine: result}} for heads a maintainer approved; tester_results: {head: {machine: result}} run
    on a tester's own trust; entry: the queue entry, or None when the PR is off the queue (stopped: who took it off;
    expired, refused: what happened to its approvals, newest last)."""
    lines = [MARK.format(pr=pr)]
    current = entry["head"] if entry else None
    if entry:
        approval = entry["approval"]
        how = {"label": "label", "command": "command", "carried": "carried over"}[approval["via"]]
        lines += [f"### Title runs for `{short(current)}` (queued by @{entry['queued_by']}, {entry['priority']})", "",
                  f"Queued `{short(current)}` for title runs: approved by @{approval['by']} ({how}, {utc(approval['at'])})."
                  + (f" Carried over from `{short(approval['from'])}`: {approval['reason']}." if approval["via"] == "carried" else ""),
                  "Each machine fetches this commit, merges it onto main locally and runs it against that main, both built on the machine in a "
                  "sandbox. Numbers are from one machine and one scene each; they are not a review.", ""]
        for push in entry.get("unapproved", []):
            lines.append(f"`{short(push['sha'])}` is the PR's head but not the approved commit: not checked. Testers run `{short(current)}`.")
        if entry.get("unapproved"):
            lines.append("")
    else:
        lines += ["### Title runs", "", "Not queued" + (f" (stopped by @{stopped})." if stopped else "."), ""]
    recent = notices(pr, expired[-1:], refused[-1:] if not entry else [], label)
    if recent:
        lines += recent + [""]
    shown = current or (expired[-1]["head"] if expired else None)
    results = by_head.get(shown, {}) if shown else {}
    combined = combined_lines(results)
    if combined:
        lines += combined + [""]
    table = rows(results)
    wanted = still_wanted(entry, results) if entry else None
    if table or wanted:
        lines += HEADER + table + ([wanted] if wanted else []) + [""]
    detail = details(results)
    if detail:
        lines += ["<details><summary>Per machine: the timed runs and summary lines</summary>", ""] + detail + ["</details>", ""]
    for head, trusted in sorted((tester_results or {}).items()):
        if trusted:
            lines += [f"**Run on the tester's trust** (`{short(head)}`, not approved by a maintainer):", ""] + HEADER + rows(trusted) + [""]
    earlier = [h for h in by_head if h != shown and by_head.get(h)]
    if earlier:
        lines += ["<details><summary>Earlier heads</summary>", ""] + HEADER
        for head in earlier:
            lines += rows(by_head[head], prefix=f"`{short(head)}` ")
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
            for name, result in results.items():
                if result["status"] != "done":
                    continue
                for title_id, entry in result["titles"].items():
                    out.setdefault(head, {}).setdefault(name, {})[title_id] = [
                        outcome_class(entry["outcome"]["A"]), outcome_class(entry["outcome"]["B"]), machine_verdict(entry)["verdict"]]
    return out


def latest(shot, order):
    out = {}
    for head in order:
        for name, titles in shot.get(head, {}).items():
            for title_id, state in titles.items():
                out[(name, title_id)] = state
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
        name, title_id = key
        for i, side in ((0, "main"), (1, "this PR")):
            if old[i] != state[i]:
                return "new", f"{name}, {title_id}: {side} went from {old[i]} to {state[i]}"
        if state[2] in ("faster", "slower") and old[2] != state[2]:
            return "new", f"{name}, {title_id}: the verdict went from {old[2]} to {state[2]}"
    return "edit", "no outcome or verdict changed"
