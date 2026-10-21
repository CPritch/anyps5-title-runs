"""What the window and the tray show, as plain data (no Qt): the Pull requests tab's four sections, the Queue tab, the
tray's state and lines. The Qt code only lays this out."""

import re

from .. import formats, rules

PERF_LABELS = ("perf", "agc", "shader")
SECTIONS = ("Queued by maintainers", "Mentions your titles", "Labelled perf, agc or shader", "Everything else")
STATES = ("idle", "running", "waiting", "error")


def title_names(config, dumps=None):
    """{title ID: short name} for the tester's titles (from the dumps' param.json when known)."""
    names = {d["title_id"]: d["name"] for d in (dumps or [])}
    return {title_id: short_name(names.get(title_id, title_id)) for title_id in config.titles}


def short_name(name):
    """"Grand Theft Auto V" -> "GTA V"; other names as they are, cut at 24 characters."""
    known = {"Grand Theft Auto V": "GTA V"}
    return known.get(name, name if len(name) <= 24 else name[:23] + "…")


def pr_sections(listing_prs, queue, titles, query="", dismissed=()):
    """The Pull requests tab: {section: [row]} with row {"number", "title", "author", "head", "priority", "titles",
    "badge", "run"}; run is True for a PR outside the queue (Run… opens the trust dialog)."""
    queued = {e["pr"]: e for e in queue.get("entries", [])}
    query = query.strip().lower()
    out = {name: [] for name in SECTIONS}
    for pr in sorted(listing_prs, key=lambda p: -p["number"]):
        if pr.get("state") != "OPEN" or pr.get("isDraft"):
            continue
        text = f"#{pr['number']} {pr['title']} {(pr.get('author') or {}).get('login', '')}".lower()
        if query and query not in text:
            continue
        row = {"number": pr["number"], "title": pr["title"], "author": (pr.get("author") or {}).get("login", ""), "head": pr.get("headRefOid", ""),
               "priority": "", "titles": "", "badge": "", "run": True}
        entry = queued.get(pr["number"])
        if entry is not None:
            row.update(priority=entry["priority"], head=entry["head"], run=False,
                       titles=", ".join(titles.get(t, t) for t in entry["titles"]) or "any",
                       badge="✓ queued" + (f" ({len(entry['unapproved'])} push not checked)" if entry.get("unapproved") else ""))
            out[SECTIONS[0]].append(row)
            continue
        if pr["number"] in dismissed:
            continue
        mine = sorted(rules.unblocks(pr.get("body")) & set(titles))
        row["badge"] = "⚠ not checked"
        if mine:
            row["titles"] = "Unblocks " + ", ".join(mine)
            out[SECTIONS[1]].append(row)
        elif rules.labels(pr) & set(PERF_LABELS):
            row["titles"] = ", ".join(sorted(rules.labels(pr) & set(PERF_LABELS)))
            out[SECTIONS[2]].append(row)
        else:
            out[SECTIONS[3]].append(row)
    return out


def waiting_for_you(sections):
    """PRs that name the tester's titles and no maintainer has queued: the tester may want to run them."""
    return sections[SECTIONS[1]]


def queue_view(ranked, status, titles):
    """The Queue tab: running, up next (with the score's reasons), waiting for you is filled by the caller, recent."""
    up_next = []
    for choice in ranked:
        entry = choice.entry
        up_next.append({"number": entry["pr"], "title": entry.get("title", ""), "head": entry["head"], "priority": entry["priority"],
                        "titles": ", ".join(titles.get(t, t) for t in entry["titles"]) or "any", "score": choice.score,
                        "reasons": choice.reasons, "unapproved": [p["sha"] for p in entry.get("unapproved", [])]})
    job = status.get("job") or {}
    running = None
    if status.get("state") == "running" and job:
        running = {"number": job.get("pr"), "head": job.get("head", ""), "line": status.get("line", ""), "progress": status.get("progress", ""),
                   "trust": job.get("trust", "queue")}
    return {"running": running, "up_next": up_next, "recent": status.get("recent", [])}


def tray_view(status, view, waiting, paused):
    """(state, [lines]) for the tray: grey idle, green running, amber waiting for you, red error."""
    lines = []
    state = status.get("state", "idle")
    if view["running"]:
        lines.append(status.get("line", "Running"))
    else:
        lines.append(status.get("line", "Idle"))
    nxt = next((u for u in view["up_next"] if u["score"] > 0 and (not view["running"] or u["number"] != view["running"]["number"])), None)
    if nxt:
        lines.append(f"Next: #{nxt['number']} · {nxt['titles']} ({nxt['priority']})")
    if waiting:
        lines.append(f"{len(waiting)} PR{'s' if len(waiting) > 1 else ''} waiting for you")
    if paused:
        lines.append(f"Paused{'' if paused == 'indefinitely' else ' until ' + formats.parse_time(paused).astimezone().strftime('%H:%M')}")
    if state not in STATES:
        state = "idle"
    if state == "idle" and waiting:
        state = "waiting"
    return state, lines


def comment_link(repository, comment_id):
    if isinstance(comment_id, int) or (isinstance(comment_id, str) and comment_id.isdigit()):
        return f"https://github.com/{repository}/issues/comments/{comment_id}"
    return ""


def first_line(text, limit=90):
    line = re.split(r"[\r\n]", text or "", maxsplit=1)[0]
    return line if len(line) <= limit else line[:limit - 1] + "…"
