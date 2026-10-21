"""The maintainers' overview (DESIGN.md, "The maintainer's controls"): the body of the pinned "Overview" issue in the
results repository, rendered from the state files each run. The client's Overview tab shows the same data."""

import json
from pathlib import Path

from .. import formats, verdict
from .render import short, utc

MARK = "<!-- anyps5-title-runs overview -->"


def results_by_job(state):
    out = {}
    for path in sorted(Path(state).glob("results/*/*.json")):
        result = json.loads(path.read_text())
        out.setdefault(result["job"], {})[result["machine"]] = result
    return out


def coverage(entry, results, rules=verdict.DEFAULT):
    """What a queue entry has and still wants: {"classes": {class: combined}, "titles": [...], "reported": n,
    "wanted": text}."""
    done = {m: r for m, r in results.items() if r["status"] == "done"}
    titles = sorted({t for r in done.values() for t in r["titles"]})
    classes = {}
    for title_id in titles:
        for key, combined in verdict.by_class(done, title_id, rules).items():
            classes[f"{key}, {title_id}"] = combined
    wanted = []
    missing = entry["machines"] - len(done)
    if missing > 0:
        wanted.append(f"{missing} more machine{'s' if missing > 1 else ''} ({', '.join(entry['hw']) or 'any hardware'})")
    for name, combined in classes.items():
        if combined["borderline"] and combined["n"] < rules.class_max:
            wanted.append(f"one more {name.split(',')[0]} (borderline)")
    missing_titles = [t for t in entry["titles"] if t not in titles]
    if missing_titles:
        wanted.append("titles " + ", ".join(missing_titles))
    return {"classes": classes, "titles": titles, "reported": len(done), "wanted": "; ".join(wanted) or "nothing"}


def view(state, queue, registry, claims, jobs, last_run, rules=verdict.DEFAULT, ignored=None):
    """The overview as data (for the client's tab and for the issue)."""
    by_job = results_by_job(state)
    at = formats.parse_time(last_run) if last_run else None  # the workflow run's time, not the reader's clock
    entries = []
    for entry in queue["entries"]:
        results = by_job.get(entry["job"], {})
        live = {m: c for m, c in (claims.get(entry["job"]) or {}).items() if not formats.claim_expired(c, at) and m not in results}
        entries.append({"entry": entry, "coverage": coverage(entry, results, rules), "claims": sorted(live), "issue": entry.get("issue")})
    last = {}
    for job, results in by_job.items():
        for name, result in results.items():
            key = formats.machine_key(result["tester"], name)
            if result.get("finished", "") > last.get(key, ""):
                last[key] = result["finished"]
    machines = [{"key": key, **m, "last_report": m.get("last_report") or last.get(key, "")} for key, m in sorted(registry["machines"].items())]
    return {"entries": entries, "machines": machines, "pending": [{"key": k, **p} for k, p in sorted(registry["pending"].items())],
            "expired": queue.get("expired", [])[-10:], "refused": queue.get("refused", [])[-10:], "last_run": last_run,
            "ignored": ignored or {"counts": {}}}


def ignored_text(ignored):
    """"5 comments from accounts without a registered machine, 1 without a title-runs payload; the last 2026-10-21 16:00
    UTC", or "" when nothing was ignored."""
    from .relay import IGNORED
    counts = (ignored or {}).get("counts") or {}
    if not counts:
        return ""
    parts = [f"{n} {IGNORED.get(reason, reason)}" for reason, n in sorted(counts.items(), key=lambda x: -x[1])]
    return "; ".join(parts) + (f" (the last {utc(ignored['last'])})" if ignored.get("last") else "")


def render(data, anyps5, label="title-test"):
    lines = [MARK, "## AnyPS5 title runs: overview", "",
             f"Updated by the relay workflow at {utc(data['last_run'])} (it runs every 5 minutes; GitHub can delay or drop scheduled runs).",
             f"Queue a PR by adding `{label}` on {anyps5}; approve a machine by adding `approved` to its registration issue here.", "",
             "### Queue", ""]
    if data["entries"]:
        lines += ["| PR | approved head | approved by | priority | reported | combined | still wanted | job |", "|---|---|---|---|---|---|---|---|"]
        for item in data["entries"]:
            e, c = item["entry"], item["coverage"]
            combined = "<br>".join(f"{v['verdict']} on {v['count']} of {v['n']} ({name})" for name, v in c["classes"].items()) or "-"
            claimed = f"; running: {', '.join(item['claims'])}" if item["claims"] else ""
            lines.append(f"| {anyps5}#{e['pr']} | `{short(e['head'])}` | @{e['approval']['by']} ({e['approval']['via']}) | {e['priority']} | "
                         f"{c['reported']} machine(s), {', '.join(c['titles']) or 'no title'}{claimed} | {combined} | {c['wanted']} | "
                         f"{'#' + str(item['issue']) if item['issue'] else '-'} |")
    else:
        lines.append("Nothing is queued.")
    lines += ["", "### Approvals a push expired", ""]
    if data["expired"]:
        lines += ["| PR | approved | expired by | pushed by | when |", "|---|---|---|---|---|"]
        lines += [f"| {anyps5}#{x['pr']} | `{short(x['head'])}` | `{short(x['by'])}` | {('@' + x['pusher']) if x.get('pusher') else '?'} | {utc(x['at'])} |"
                  for x in reversed(data["expired"])]
    else:
        lines.append("None.")
    if data["refused"]:
        lines += ["", "### Labels that came after the head", "", "| PR | label by | head | pushed |", "|---|---|---|---|"]
        lines += [f"| {anyps5}#{x['pr']} | @{x['by']} ({utc(x['labelled'])}) | `{short(x['head'])}` | {utc(x['pushed'])} |" for x in reversed(data["refused"])]
    lines += ["", "### Machines", ""]
    if data["machines"]:
        lines += ["| tester / machine | class | titles | approved by | last report |", "|---|---|---|---|---|"]
        lines += [f"| {m['key']} | {verdict.class_of(m['class'])} | {', '.join(m.get('titles', [])) or '-'} | @{m['approved_by']} | "
                  f"{utc(m['last_report']) if m.get('last_report') else 'never'} |" for m in data["machines"]]
    else:
        lines.append("No machine is registered yet.")
    lines += ["", "### Pending registrations", ""]
    if data["pending"]:
        lines += ["| issue | tester / machine | class | titles |", "|---|---|---|---|"]
        lines += [f"| #{p['issue']} | {p['key']} | {verdict.class_of(p['class'])} | {', '.join(p.get('titles', [])) or '-'} |" for p in data["pending"]]
        lines += ["", "Add the label `approved` to a registration issue to approve the machine, or `declined` to turn it down."]
    else:
        lines.append("None.")
    lines += ["", "### Ignored, without a reply", ""]
    lines.append((ignored_text(data.get("ignored")) + ". The workflow answers nothing it does not use, so commenting cannot make it write.")
                 if ignored_text(data.get("ignored")) else "Nothing.")
    return "\n".join(lines) + "\n"
