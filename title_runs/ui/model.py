"""What the window and the tray show, as plain data (no Qt): the All pull requests page's four sections, the main
screen's header and steps, the tray's state and lines. The Qt code only lays this out."""

import re

from .. import rules

PERF_LABELS = ("perf", "agc", "shader")
SECTIONS = ("On your local tests", "Mentions your titles", "Labelled perf, agc or shader", "Everything else")
STATES = ("idle", "running", "waiting", "error")


def title_names(config, dumps=None):
    """{title ID: short name} for the tester's titles (from the dumps' param.json when known)."""
    names = {d["title_id"]: d["name"] for d in (dumps or [])}
    return {title_id: short_name(names.get(title_id, title_id)) for title_id in config.titles}


def short_name(name):
    """"Grand Theft Auto V" -> "GTA V"; other names as they are, cut at 24 characters."""
    known = {"Grand Theft Auto V": "GTA V"}
    return known.get(name, name if len(name) <= 24 else name[:23] + "…")


def pr_sections(listing_prs, listed, titles, query="", dismissed=()):
    """The All pull requests page: {section: [row]} with row {"number", "title", "author", "head", "titles", "badge",
    "add"}, from the listing's open pull requests (listing.shape); add is True for a PR not on the local tests list
    (listed, its numbers)."""
    query = query.strip().lower()
    out = {name: [] for name in SECTIONS}
    for pr in sorted(listing_prs, key=lambda p: -p["number"]):
        if pr.get("draft"):
            continue
        text = f"#{pr['number']} {pr['title']} {pr.get('author', '')}".lower()
        if query and query not in text:
            continue
        row = {"number": pr["number"], "title": pr["title"], "author": pr.get("author", ""), "head": pr.get("head", ""),
               "titles": "", "badge": "", "add": True}
        if pr["number"] in listed:
            row.update(add=False, badge="✓ on your list")
            out[SECTIONS[0]].append(row)
            continue
        if pr["number"] in dismissed:
            continue
        mine = sorted(rules.unblocks(pr.get("body")) & set(titles))
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
    """PRs that name the tester's titles and aren't on the local tests list: the tester may want to add them."""
    return sections[SECTIONS[1]]


def tray_view(status, up_next, waiting, testing):
    """(state, [lines]) for the tray: grey idle, green running, amber waiting for you, red error. up_next: the heads
    waiting to be tested, without the one running."""
    state = status.get("state", "idle")
    lines = [status.get("line", "Running" if state == "running" else "Idle")]
    nxt = next(iter(up_next), None)
    if nxt:
        lines.append(f"Next: #{nxt['number']} {first_line(nxt['title'], 60)}")
    if waiting:
        lines.append(f"{len(waiting)} pull request{'s mention' if len(waiting) > 1 else ' mentions'} your games")
    if testing != "schedule":
        lines.append(TESTING[testing][1])
    if state not in STATES:
        state = "idle"
    if state == "idle" and waiting:
        state = "waiting"
    return state, lines


def first_line(text, limit=90):
    line = re.split(r"[\r\n]", text or "", maxsplit=1)[0]
    return line if len(line) <= limit else line[:limit - 1] + "…"


# -- the main screen (ui/home.py) ----------------------------------------------------------------------------------------

def setup_text(why):
    """What a tester still has to do (or wait for), for a reason client.ready gave."""
    return {"the first-run walkthrough is not done": "Go through the first-run steps.",
            "no titles are set up": "Add a game you own."}.get(why, why)


STEPS = ("Downloading the change", "Building AnyPS5 without the change", "Building AnyPS5 with the change", "Warming up the game",
         "Run 1 of 4: without the change", "Run 2 of 4: with the change", "Run 3 of 4: without the change", "Run 4 of 4: with the change",
         "Writing the report")


def waiting_for(why):
    """When the next test can start, to follow "The next test starts", for a reason client.allowed_now gave."""
    found = re.match(r"outside the hours (\d+)-(\d+)", why)
    if found:
        return f"between {found.group(1)}:00 and {found.group(2)}:00 (your chosen hours)"
    if why == "on battery":
        return "when the computer is plugged in"
    if why.endswith(" is running"):
        return f"when {why[:-len(' is running')]} closes"
    if why.startswith("in use"):
        return "once you've left the computer alone for a while"
    if why == "paused":
        return "when you switch testing back on"
    if why.startswith("paused until"):
        return why.replace("paused until", "after")
    return f"when this is sorted: {why}"


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


TESTING = {"off": ("Off", "Testing is off."),
           "schedule": ("On schedule", "Tests run automatically at the times you chose."),
           "now": ("Now", "Tests run one after another, even outside your chosen times, until you switch back.")}


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


def header(status, ready, why, testing, allowed, allowed_why, best):
    """The main screen's header: {"kind", "headline", "detail"}; kind is running, setup, error, idle, off, waiting or
    ready. best: the next head to be tested, or None."""
    job = status.get("job") or {}
    if status.get("state") == "running" and job.get("recording"):
        return {"kind": "running", "headline": f"Recording a scenario: {job.get('title', '')}", "detail": status.get("progress", ""), "step": -1}
    if status.get("state") == "running" and job:
        return {"kind": "running", "headline": f"Testing #{job.get('pr')}" + (f": {job['title']}" if job.get("title") else ""),
                "detail": STEPS[step(status.get("progress"))], "step": step(status.get("progress"))}
    if not ready:
        return {"kind": "setup", "headline": "Almost ready", "detail": setup_text(why)}
    if status.get("state") == "error":
        return {"kind": "error", "headline": "The last test failed", "detail": first_line(status.get("line", ""), 160)}
    if best is None:
        return {"kind": "idle", "headline": "Nothing to test", "detail": "When a pull request on your list gets new commits, they're tested next."}
    if testing == "off":
        return {"kind": "off", "headline": "Testing is off", "detail": "Choose On schedule or Now to start testing."}
    if testing == "now":
        return {"kind": "ready", "headline": "Starting the next test", "detail": "It starts within a minute."}
    if not allowed:
        return {"kind": "waiting", "headline": "Waiting", "detail": f"The next test starts {waiting_for(allowed_why)}."}
    return {"kind": "ready", "headline": "Starting the next test", "detail": "It starts within a minute."}
