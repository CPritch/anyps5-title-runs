"""What the window and the tray show, as plain data (no Qt): the Pull requests tab's four sections, the Queue tab, the
tray's state and lines. The Qt code only lays this out."""

import re

from .. import formats, rules
from . import words

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
    job = status.get("job") or {}
    for choice in ranked:
        entry = choice.entry
        if status.get("state") == "running" and job.get("pr") == entry["pr"] and job.get("head") == entry["head"]:
            continue
        up_next.append({"number": entry["pr"], "title": entry.get("title", ""), "head": entry["head"], "priority": entry["priority"],
                        "titles": ", ".join(titles.get(t, t) for t in entry["titles"]) or "any", "score": choice.score,
                        "reasons": choice.reasons, "unapproved": [p["sha"] for p in entry.get("unapproved", [])]})
    running = None
    if status.get("state") == "running" and job:
        running = {"number": job.get("pr"), "head": job.get("head", ""), "line": status.get("line", ""), "progress": status.get("progress", ""),
                   "trust": job.get("trust", "queue")}
    return {"running": running, "up_next": up_next, "recent": status.get("recent", [])}


def tray_view(status, view, waiting, testing):
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
    if testing != "schedule":
        lines.append(TESTING[testing][1])
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


# -- the main screen (ui/home.py), in the words a tester reads ----------------------------------------------------------

def setup_text(why):
    """What a tester still has to do (or wait for), for a reason client.ready gave."""
    return {"the first-run walkthrough is not done": "Go through the first-run steps.",
            "no titles are set up": "Add a game you own.",
            "not signed in": "Sign in with GitHub.",
            "this machine is not registered": "Register this machine.",
            "waiting for a maintainer to approve this machine": f"{words.Team()} still has to approve this machine. Nothing to do but wait.",
            "a maintainer declined this machine": f"{words.Team()} turned this machine down."}.get(why, why)

STEPS = ("Getting the change", "Building AnyPS5 as it is", "Building AnyPS5 with the change", "Warming up the game",
         "Run 1 of 4: as it is", "Run 2 of 4: with the change", "Run 3 of 4: as it is", "Run 4 of 4: with the change", "Sending the result")


def waiting_for(why):
    """When the next test may start, for a reason client.allowed_now gave."""
    found = re.match(r"outside the hours (\d+)-(\d+)", why)
    if found:
        return f"between {found.group(1)}:00 and {found.group(2)}:00, the hours you chose"
    if why == "on battery":
        return "the computer is plugged in"
    if why.endswith(" is running"):
        return f"{why[:-len(' is running')]} has closed"
    if why.startswith("in use"):
        return "the computer has been left alone for a while"
    if why == "paused":
        return "when you switch testing back on"
    if why.startswith("paused until"):
        return why.replace("paused until", "after")
    return why


def step(progress):
    """The index in STEPS of what the job is doing, from its progress text (job.run's stages, protocol's runs)."""
    text = progress or ""
    found = re.search(r"(main|PR) run \d+, (\d)/4", text)
    if found:
        return 3 + int(found.group(2))
    if "warm-up" in text:
        return 3
    if text.startswith("B:"):
        return 2
    if text.startswith("A:"):
        return 1
    if "result" in text or "report" in text:
        return 8
    return 0


TESTING = {"off": ("Off", "Testing is off: no test starts."),
           "schedule": ("On schedule", "Tests start by themselves at the times you chose."),
           "now": ("Now", "Testing now: one test after another, whatever the time, until you switch back.")}


def schedule_words(rules, idle_detectable=True):
    """The schedule in a sentence: "between 01:00 and 07:00, when the computer is plugged in and nothing is fullscreen"."""
    conditions = []
    if rules.get("idle_only", True) and idle_detectable:
        conditions.append(f"you've been away for {rules.get('idle_minutes', 10)} minutes")
    if rules.get("mains_only", True):
        conditions.append("the computer is plugged in")
    if rules.get("pause_fullscreen", True):
        conditions.append("nothing is fullscreen")
    when = "when " + (", ".join(conditions[:-1]) + " and " if len(conditions) > 1 else "") + conditions[-1] if conditions else ""
    first, last = rules.get("hours", [0, 24])
    hours = f"between {first:02d}:00 and {last:02d}:00" if (first, last) != (0, 24) else ""
    return ", ".join(part for part in (hours, when) if part) or "at any time"


def header(status, ready, why, testing, allowed, allowed_why, best, local_only=False):
    """The main screen's header: {"kind", "headline", "detail"}; kind is running, setup, off, idle, waiting or ready.
    local_only: no results repository, so the only tests are the tester's local ones."""
    job = status.get("job") or {}
    if status.get("state") == "running" and job:
        return {"kind": "running", "headline": f"Testing #{job.get('pr')}" + (f": {job['title']}" if job.get("title") else ""),
                "detail": STEPS[step(status.get("progress"))], "step": step(status.get("progress"))}
    if not ready:
        return {"kind": "setup", "headline": "Almost ready", "detail": setup_text(why)}
    if status.get("state") == "error":
        return {"kind": "error", "headline": "The last test went wrong", "detail": first_line(status.get("line", ""), 160)}
    if best is None:
        return {"kind": "idle", "headline": "No tests waiting",
                "detail": "New heads of your local tests show up here by themselves." if local_only else f"New tests from {words.team()} show up here by themselves."}
    if testing == "off":
        return {"kind": "off", "headline": "Testing is off", "detail": "Choose On schedule or Now to start testing."}
    if testing == "now":
        return {"kind": "ready", "headline": "Starting the next test", "detail": "Testing now, whatever the time. It starts within a minute."}
    if not allowed:
        return {"kind": "waiting", "headline": "Waiting", "detail": f"The next test starts by itself {waiting_for(allowed_why)}."}
    return {"kind": "ready", "headline": "Starting the next test", "detail": "It starts within a minute."}


def plain_reason(choice):
    """Why a queued test is or isn't up next for this machine, from schedule.score's factors."""
    reasons = " ".join(choice.reasons)
    if choice.score > 0:
        return "Next" if choice.factors.get("coverage", 1) >= 1 else "Wanted, after the others"
    if "this machine has reported" in reasons:
        return "Already tested on this machine"
    if "holds a claim" in reasons:
        return "Another machine like yours is testing it"
    if "machine(s) wanted" in reasons:
        return "Enough machines have tested it"
    if "hardware wanted" in reasons:
        return "Wants other hardware"
    if "titles wanted" in reasons:
        return "Wants a game you haven't added"
    return "Not for this machine"


def up_next(ranked, status):
    """The tests in the queue for this machine, best first, without the one running."""
    job = status.get("job") or {}
    rows = []
    for choice in ranked:
        entry = choice.entry
        if status.get("state") == "running" and job.get("pr") == entry["pr"] and job.get("head") == entry["head"]:
            continue
        rows.append({"number": entry["pr"], "title": entry.get("title", ""), "author": entry.get("author", ""), "head": entry["head"],
                     "queued_by": entry.get("queued_by", ""), "queued_at": entry.get("queued_at", ""), "score": choice.score,
                     "why": plain_reason(choice), "reasons": choice.reasons})
    return rows


def recent(status, results, machine, rules_):
    """The tests this machine reported, newest first, with each one's verdict: [{"number", "head", "at", "status",
    "verdict"}]. results: the results repository's {job: {machine: result}}."""
    from .. import verdict
    out = []
    for row in status.get("recent", []):
        result = (results.get(formats.job_id(row["pr"], row["head"])) or {}).get(machine)
        words = row["status"]
        if result and result.get("status") == "done":
            parts = []
            for title_id, entry in sorted(result["titles"].items()):
                v = verdict.machine(entry.get("sides") or {}, rules_)
                if v.get("diff") is None:
                    parts.append(f"{title_id}: not enough runs counted")
                else:
                    word = {"faster": "Faster", "slower": "Slower"}.get(v["verdict"], "No difference")
                    parts.append(f"{word} ({v['diff']:+.2f} ms)" + (", borderline" if v.get("borderline") else ""))
            words = "; ".join(parts) or words
        out.append({"number": row["pr"], "head": row["head"], "at": row.get("at", ""), "status": row["status"], "verdict": words})
    return out
