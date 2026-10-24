"""title-runs: the command line, for people and for agents.

Every command is in COMMANDS: its group, a one-line summary, what it does, what it changes, the JSON it prints with
--json, and examples. The parser, `title-runs help` and docs/CLI.md are all made from that table, so they can't
disagree. The commands drive the same engine as the window (engine.py), from the same config and state folder, and
can run while the window is open (locks.py).
"""

import argparse
import html
import io
import json
import os
import re
import signal
import sys
import textwrap
import threading
from contextlib import redirect_stdout
from dataclasses import dataclass, field
from pathlib import Path

from . import config as configs

EXIT_OK, EXIT_FAILED, EXIT_USAGE = 0, 1, 2
CONFIG_ENV = "TITLE_RUNS_CONFIG"

GROUPS = {
    "computer": "This computer",
    "local": "Local tests (pull requests you choose, tested on this computer)",
    "games": "Your games and the window",
}

NOTHING = "Nothing."
SETTINGS = "This computer's settings (the config file)."


class Failed(Exception):
    """A command couldn't do what it was asked; the message says why, in words for the person (exit 1)."""


@dataclass
class Command:
    path: tuple  # ("local", "add")
    group: str
    summary: str
    description: str = ""
    changes: str = NOTHING
    json: str = ""
    examples: tuple = ()
    arguments: object = None  # arguments(parser): adds the command's own
    run: object = None  # run(ctx, args) -> Out
    passthrough: object = None  # main(argv): a command with a parser of its own (window)
    hidden: bool = False

    @property
    def name(self):
        return " ".join(self.path)


@dataclass
class Out:
    text: object = ""  # a string or a list of lines
    data: dict = field(default_factory=dict)


# -- helpers ---------------------------------------------------------------------------------------------------------

def plain(text):
    """The window's rich text (<b>, <br>, links) as plain text."""
    text = re.sub(r"<br\s*/?>", "\n", text or "")
    return html.unescape(re.sub(r"<[^>]+>", "", text)).strip()


def short(sha):
    return (sha or "")[:9]


def when(iso):
    if not iso:
        return ""
    from .formats import utc_text
    return utc_text(iso)


def pr_number(text):
    found = re.fullmatch(r"#?(\d+)|https://github\.com/[^/]+/[^/]+/pull/(\d+)\S*", str(text).strip())
    if not found:
        raise Failed(f"{text!r} is not a pull request number or link")
    return int(found.group(1) or found.group(2))


SWITCH = {"off": "Testing is off.",
          "schedule": "Testing is on schedule. Tests run automatically at the times you chose.",
          "now": "Testing is on now. Tests run one after another, even outside your chosen times, until you switch back."}


def megabytes(size):
    return f"{size / 1e6:.1f} MB" if size is not None else "no trace kept"


class Context:
    """The config and the engine, made when a command first needs them."""

    def __init__(self, args, echo):
        self.args, self.echo = args, echo
        self._config = self._engine = None

    @property
    def config(self):
        if self._config is None:
            path = Path(self.args.config).expanduser()
            if not path.exists():
                raise Failed(f"No config at {path}. Open the window once to make one (title-runs window), or name one with --config FILE.")
            try:
                self._config = configs.load(path)
            except (configs.ConfigError, ValueError) as error:
                raise Failed(f"{path}: {error}") from error
        return self._config

    @property
    def engine(self):
        if self._engine is None:
            from .engine import Engine
            self._engine = Engine(self.config)
            if getattr(self.args, "command_path", None) == ("run",):  # what the worker does, as it does it
                quiet = self._engine.log

                def both(text):
                    quiet(text)
                    self.echo(text)
                self._engine.log = self._engine.local.log = both
        return self._engine


def newest_result(engine, number, test=1):
    results = engine.local_results(number)
    if not results:
        raise Failed(f"#{number} has no local result yet (title-runs local list).")
    if not 1 <= test <= len(results):
        raise Failed(f"#{number} has {len(results)} result{'s' if len(results) != 1 else ''}; --test takes 1 to {len(results)}.")
    return results[test - 1]


# -- this computer -----------------------------------------------------------------------------------------------------

def run_status(ctx, args):
    from .ui import model
    engine = ctx.engine
    header = engine.home()
    status = engine.status()
    job = status.get("job") or {}
    running = None
    if status.get("state") == "running" and job:
        running = {"pr": job.get("pr"), "head": job.get("head", ""), "title": job.get("title", ""), "step": model.STEPS[model.step(status.get("progress"))],
                   "progress": status.get("progress", "")}
    nxt = next(iter(engine.up_next_rows()), None)
    notes = [plain(n) for n in (engine.local_notice(),) if n]
    data = {"headline": header["headline"], "detail": plain(header["detail"]), "kind": header["kind"], "testing": ctx.config.testing,
            "running": running, "busy_elsewhere": engine.busy_elsewhere(),
            "next": {"pr": nxt["number"], "title": nxt["title"], "head": nxt["head"]} if nxt else None,
            "notes": notes, "machine": ctx.config.machine, "project": ctx.config.local_repository,
            "config": str(ctx.config.path), "state": str(ctx.config.state_dir)}
    # in the window's order: the header, the notices, then the switch
    lines = [SWITCH["off"] + " To start testing: title-runs testing schedule (or now)." if header["kind"] == "off" else f"{header['headline']}. {plain(header['detail'])}"]
    if running:
        lines.append(f"Step: {running['step']}" + (f" ({running['progress']})" if running["progress"] else ""))
    lines += notes
    if header["kind"] != "off":
        lines.append(SWITCH[ctx.config.testing])
    if nxt and not running:
        lines.append(f"Up next: #{nxt['number']} {nxt['title']}")
    lines.append(f"This computer: {ctx.config.machine}. Config {ctx.config.path}")
    return Out(lines, data)


def run_testing(ctx, args):
    engine = ctx.engine
    if args.mode:
        engine.set_testing(args.mode)
    return Out(SWITCH[ctx.config.testing], {"testing": ctx.config.testing, "meaning": SWITCH[ctx.config.testing]})


def run_stop(ctx, args):
    engine = ctx.engine
    status = engine.status()
    running = (status.get("job") or {}).get("pr") if status.get("state") == "running" else None
    engine.stop()
    text = (f"Stopping #{running}: it ends within a few seconds, and it waits to be tested again." if running else "No test was running.") + " Testing is off."
    return Out(text, {"stopped": running, "testing": "off"})


def run_run(ctx, args):
    engine = ctx.engine
    if not engine.client.onboarded():
        raise Failed("Go through the first-run steps first (title-runs window). Nothing runs before then.")
    if args.once:
        engine.refresh_local(force=True)
        done = engine.next_test(now=True)
        return Out(done, {"result": done})
    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    ctx.echo("Testing here as the switch and the schedule allow. Ctrl+C ends it, and the test running.")
    engine.start()
    while not stop.wait(1) and engine.thread.is_alive():
        pass
    engine.shutdown()
    return Out("Stopped.", {"result": "stopped"})


def run_check(ctx, args):
    engine = ctx.engine
    sandbox = engine.sandbox_self_test()
    ready, why, _ = engine.readiness()
    games = [{"title_id": t["title_id"], "name": t["name"], "test": t["check"], "scenario": t["scenario"], "folder": t["path"]} for t in engine.titles()]
    controller = engine.controller()
    data = {"sandbox": sandbox, "sandbox_ok": sandbox.startswith("The sandbox works"), "ready": ready, "why": why, "games": games,
            "controller": controller}
    lines = [sandbox, "Ready to test." if ready else f"Not ready: {plain(why)}.",
             f"Controller for recording: {controller['name']} ({controller['path']})." if controller else
             "No game controller connected (only recording a scenario needs one)."]
    lines += [f"{g['title_id']} {g['name']}: {g['test'].lower()}" + (f", scenario {g['scenario']}" if g["scenario"] else "") for g in games] or ["No games set up."]
    return Out(lines, data)


def run_log(ctx, args):
    lines = ctx.engine.log_tail(args.lines).splitlines()
    return Out(lines, {"lines": lines})


# -- local tests -------------------------------------------------------------------------------------------------------

def local_row(row):
    entry = row["entry"]
    state = {"queued": "waiting", "done": "tested", "failed": "failed", "skipped": "not tested"}.get(entry["status"], entry["status"])
    return {"pr": row["pr"], "title": row["title"], "author": row["author"], "state": state, "head": entry["head"],
            "verdict": entry.get("verdict") or entry.get("reason", ""), "at": entry.get("at", ""), "main": entry.get("main", ""),
            "report": row.get("report", ""), "stale": row.get("stale", ""), "earlier": len(row.get("earlier", [])), "removed": row.get("removed", False)}


def run_local_list(ctx, args):
    engine = ctx.engine
    rows = [local_row(r) for r in engine.local_rows()]
    data = {"repository": ctx.config.local_repository, "main": engine.local_base(), "people": list(ctx.config.local_people),
            "fixes": list(ctx.config.local_fixes), "prs": rows}
    if not ctx.config.local_repository:
        return Out("No project for local tests yet: title-runs local repository OWNER/NAME.", data)
    lines = [f"Local tests of {ctx.config.local_repository}, against {engine.local_base()}."]
    if engine.local_notice():
        lines.append(plain(engine.local_notice()))
    for r in rows:
        if r["state"] == "waiting":
            what = "waiting to be tested"
        elif r["state"] == "tested":
            what = f"{r['verdict']}, {when(r['at'])}, {r['report'].lower() or 'not posted'}" + (f" ({r['earlier']} earlier)" if r["earlier"] else "")
        elif r["state"] == "not tested":
            what = f"not tested: {r['verdict']}" if r["verdict"] else "not tested"
        else:
            what = r["verdict"] or r["state"]
        lines.append(f"#{r['pr']} {r['title']} ({r['author']}): {what}")
    if not rows:
        lines.append("Nothing yet: title-runs local add PR.")
    return Out(lines, data)


def run_local_add(ctx, args):
    engine = ctx.engine
    numbers = []
    for text in args.prs:
        number, why = engine.local.parse(text)  # a link to another repository's pull request is refused, as in the window
        if number is None:
            raise Failed(why)
        numbers.append(number)
    said = [engine.local_add(str(number)) for number in numbers]
    return Out(said, {"added": numbers})


def run_local_remove(ctx, args):
    engine = ctx.engine
    numbers = [pr_number(t) for t in args.prs]
    for number in numbers:
        engine.local_remove(number)
    return Out(f"Removed {', '.join('#' + str(n) for n in numbers)}. Their results stay.", {"removed": numbers})


def run_local_again(ctx, args):
    number = pr_number(args.pr)
    head = ctx.engine.local_again(number)
    if head is None:
        raise Failed(f"#{number} hasn't been tested yet, or it's already waiting to be tested again.")
    return Out(f"#{number} at {short(head)} will be tested again. Its earlier result is kept.", {"pr": number, "head": head})


def traces_of(engine, result):
    folder, files = engine.local_attachments(result["entry"])
    return str(folder), [{"name": f["name"], "path": str(f["file"]) if f.get("file") else None, "size": f["size"], "fits": f["fits"],
                          "run": f["words"]} for f in files]


def run_local_report(ctx, args):
    engine = ctx.engine
    number = pr_number(args.pr)
    result = newest_result(engine, number, args.test)
    entry = result["entry"]
    folder, traces = traces_of(engine, result)
    data = {"pr": number, "link": result["link"], "head": entry["head"], "at": entry.get("at", ""), "verdict": entry.get("verdict", ""),
            "stale": result["stale"], "posted": bool(entry.get("posted")), "text": result["text"], "traces": traces, "folder": folder}
    if args.text:
        return Out(result["text"].rstrip("\n"), data)
    lines = [f"Post it on {result['link']}"]
    if result["stale"]:
        lines.append(f"Out of date: {result['stale']}. Test it again before posting (title-runs local again {number}).")
    if entry.get("posted"):
        lines.append(f"You marked it posted on {when(entry['posted']['at'])}.")
    if traces:
        fit = [t for t in traces if t["fits"]]
        lines.append(f"Traces to attach: {len(fit)} of {len(traces)}, in {folder} (title-runs local files {number})" +
                     ("." if len(fit) == len(traces) else "; the others are over GitHub's 25 MB, so this report lacks what the project's form asks for."))
    lines += ["", result["text"].rstrip("\n")]
    return Out(lines, data)


def run_local_files(ctx, args):
    engine = ctx.engine
    number = pr_number(args.pr)
    folder, traces = traces_of(engine, newest_result(engine, number, args.test))
    lines = [f"Drag these into the comment under Traces, from {folder}:"]
    lines += [f"  {t['name']}  {megabytes(t['size'])}" + ("" if t["fits"] or t["size"] is None else ", over GitHub's 25 MB limit, so it can't be attached")
              for t in traces] or ["  (this result has no traces)"]
    return Out(lines, {"pr": number, "folder": folder, "traces": traces})


def run_local_posted(ctx, args):
    engine = ctx.engine
    number = pr_number(args.pr)
    entry = newest_result(engine, number, args.test)["entry"]
    engine.local_posted(number, entry["head"], not args.undo, entry.get("at"))
    return Out(f"#{number} at {short(entry['head'])}: marked {'not ' if args.undo else ''}posted.", {"pr": number, "head": entry["head"], "posted": not args.undo})


def run_local_follow(ctx, args, follow=True):
    engine = ctx.engine
    people = list(ctx.config.local_people)
    for login in args.people:
        if follow and login not in people:
            people.append(login)
        if not follow and login in people:
            people.remove(login)
    engine.local_save(ctx.config.local_repository, people, list(ctx.config.local_fixes))
    return Out(f"Following {', '.join(people) or 'nobody'}.", {"people": people})


def run_local_fixes(ctx, args):
    engine = ctx.engine
    if args.prs or args.none:
        engine.local_save(ctx.config.local_repository, list(ctx.config.local_people), [] if args.none else [pr_number(t) for t in args.prs])
    fixes = list(ctx.config.local_fixes)
    text = (f"Fixes merged into both builds: {', '.join('#' + str(n) for n in fixes)} (any that main already includes are skipped)." if fixes
            else "No fixes: both builds are main as it is.")
    return Out(text, {"fixes": fixes})


def run_local_main(ctx, args):
    engine = ctx.engine
    if args.latest:
        engine.local_unpin()
    base = engine.local_base()
    return Out(f"Local tests are tested against {base}.", {"main": base, "pinned": engine.local.pinned()})


def run_local_repository(ctx, args):
    engine = ctx.engine
    if args.repository:
        if not re.fullmatch(r"[A-Za-z0-9-]+/[A-Za-z0-9._-]+", args.repository):
            raise Failed(f"{args.repository!r} is not OWNER/NAME")
        engine.local_save(args.repository, list(ctx.config.local_people), list(ctx.config.local_fixes))
    repository = ctx.config.local_repository
    return Out(f"Local tests are pull requests of {repository}." if repository else "No project for local tests yet.", {"repository": repository})


# -- your account, your games and the window -------------------------------------------------------------------------------

def run_games(ctx, args):
    games = [{"title_id": t["title_id"], "name": t["name"], "version": t["version"], "test": t["check"], "scenario": t["scenario"],
              "scenarios": [s["id"] for s in t["scenarios"]], "folder": t["path"]} for t in ctx.engine.titles()]
    lines = [f"{g['title_id']} {g['name']} {g['version']}: {g['test'].lower()}" + (f" in {g['scenario']} (of {', '.join(g['scenarios'])})" if g["scenario"] else "")
             + f"\n    {g['folder']}" for g in games] or ["No games set up: add them in the window's Settings."]
    return Out(lines, {"games": games})


def run_games_scenario(ctx, args):
    from . import scenarios
    engine = ctx.engine
    title = engine.config.titles.get(args.title_id)
    if title is None:
        raise Failed(f"{args.title_id} is not one of your games (title-runs games).")
    found = scenarios.available(args.title_id, engine.config.state_dir)
    if args.scenario:
        if args.scenario not in found:
            raise Failed(f"{args.title_id} has no scenario {args.scenario!r}; it has {', '.join(found) or 'none'}.")
        engine.set_scenario(args.title_id, args.scenario)
    current = title.scenario or next((key for key, s in found.items() if s.get("default")), "")
    lines = [f"{args.title_id} is tested in {current or 'its route'}."] + [f"  {key}: {s['name']}. {s['scene']}" for key, s in found.items()]
    return Out(lines, {"title_id": args.title_id, "scenario": current,
                       "scenarios": [{"id": key, "name": s["name"], "scene": s["scene"]} for key, s in found.items()]})


def run_games_record(ctx, args):
    from . import pad, recording
    engine = ctx.engine
    taken = scenarios_of(engine, args.title_id)
    scenario_id = args.id or recording.new_id(args.name, taken)
    try:
        path = engine.record_scenario(args.title_id, args.start, scenario_id, args.name, args.scene, args.seconds,
                                      say=lambda text: ctx.echo(text, {"progress": text}))
    except (recording.RecordError, pad.PadError) as error:
        raise Failed(f"Not recorded: {error}") from error
    return Out(f"Recorded {args.name} as {scenario_id} ({path}). To test {args.title_id} in it: title-runs games scenario {args.title_id} {scenario_id}",
               {"recorded": scenario_id, "path": str(path)})


def scenarios_of(engine, title_id):
    from . import scenarios
    return scenarios.available(title_id, engine.config.state_dir)


# -- commands with a parser of their own ---------------------------------------------------------------------------------

def window_main(argv):
    from .ui.app import main as window
    return window(argv)


# -- the table -----------------------------------------------------------------------------------------------------------

def _pr(p):
    p.add_argument("pr", metavar="PR", help="a pull request's number or link")


def _test(p):
    p.add_argument("--test", type=int, default=1, metavar="N", help="which result: 1 is the newest (the default), 2 the one before")


COMMANDS = [
    Command(("status",), "computer", "What this computer is doing: the test running, the testing switch, what's next, anything to fix.",
            "Shows the test running on this computer (from the window, `title-runs run`, or here), the testing switch, the next "
            "test, and anything that's stopping tests from starting.",
            NOTHING,
            '{"headline", "detail", "kind": "running|setup|off|idle|waiting|ready|error", "testing", "running": {"pr", "head", "title", '
            '"step", "progress"} or null, "busy_elsewhere", "next": {"pr", "title", "head"} or null, "notes": [...], '
            '"machine", "project", "config", "state"}',
            ("title-runs status", "title-runs --json status"), None, run_status),
    Command(("testing",), "computer", "Show or set the testing switch: off, schedule or now.",
            "off: no tests start. schedule: tests run automatically at the times set in the window's When to test. now: tests run "
            "one after another, even outside those times, until you switch back. Switching doesn't end a running test; "
            "`title-runs stop` does. An open window picks up the change within a few seconds.",
            SETTINGS + " Only when a mode is given.", '{"testing": "off|schedule|now", "meaning"}',
            ("title-runs testing", "title-runs testing now", "title-runs testing off"),
            lambda p: p.add_argument("mode", nargs="?", choices=configs.TESTING, help="off, schedule or now"), run_testing),
    Command(("stop",), "computer", "End the running test now, and set testing to off.",
            "Ends the test running on this computer, whether it was started from the window or `title-runs run`. Its build or game "
            "stops within a few seconds, and the pull request waits to be tested again. Testing is switched off, so another test "
            "doesn't start a minute later.",
            SETTINGS + " Testing goes to off.", '{"stopped": PR or null, "testing": "off"}', ("title-runs stop",), None, run_stop),
    Command(("run",), "computer", "Run tests here without the window, when the switch and the schedule allow, until stopped.",
            "Does what the open window does in the background: runs your local tests whenever the testing switch and the schedule "
            "allow. It runs until Ctrl+C, which also ends the running test. --once starts one test now, ignoring the switch and the "
            "schedule, and exits when it's done. Only one test runs on a computer at a time, so while the window is testing this "
            "waits, and the other way round. Nothing runs until the first-run steps (`title-runs window`) are done.",
            "Builds and runs tests on this computer. Their results stay here.",
            'one object per line: {"log": text} as it goes, then {"result": text}',
            ("title-runs run", "title-runs run --once", "title-runs --json run --once"),
            lambda p: p.add_argument("--once", action="store_true", help="one test now, ignoring the switch, then exit"), run_run),
    Command(("check",), "computer", "Check this computer can test: the sandbox, your games and a controller to record with.",
            "Runs the sandbox's self-test (no internet or files of yours inside, risky system calls blocked, the graphics card "
            "available to the game), and says whether anything else is stopping tests from starting.",
            NOTHING, '{"sandbox", "sandbox_ok", "ready", "why", "games": [{"title_id", "name", "test", "scenario", "folder"}], '
            '"controller": {"name", "path"} or null}',
            ("title-runs check",), None, run_check),
    Command(("log",), "computer", "The last lines of this computer's log, and of the latest test's.", "", NOTHING, '{"lines": [...]}',
            ("title-runs log", "title-runs log --lines 50"),
            lambda p: p.add_argument("--lines", type=int, default=20, help="how many of each (default 20)"), run_log),

    Command(("local", "list"), "local", "Your local tests: what's waiting, and each pull request's newest result.",
            "`title-runs local` on its own does the same. Each pull request shows its newest result, whether its report has been "
            "posted or is out of date, and how many earlier results it has.",
            NOTHING, '{"repository", "main", "people", "fixes", "prs": [{"pr", "title", "author", "state": "waiting|tested|failed|not tested", '
            '"head", "verdict", "at", "main", "report": "Posted|Out of date: why|Not posted", "stale", "earlier", "removed"}]}',
            ("title-runs local", "title-runs --json local list"), None, run_local_list),
    Command(("local", "add"), "local", "Add pull requests to your local tests, by number or link.",
            "Each commit the pull request's author pushes is tested once against the project's main, when testing allows. Commits "
            "pushed by anyone else aren't tested. An open window shows them within a minute.",
            "Your local tests list and settings.", '{"added": [PR, ...]}',
            ("title-runs local add 4287", "title-runs local add 9287 9289"),
            lambda p: p.add_argument("prs", nargs="+", metavar="PR", help="numbers or links"), run_local_add),
    Command(("local", "remove"), "local", "Take pull requests off your local tests; their results stay.", "",
            "Your local tests list and settings.", '{"removed": [PR, ...]}', ("title-runs local remove 8566",),
            lambda p: p.add_argument("prs", nargs="+", metavar="PR", help="numbers or links"), run_local_remove),
    Command(("local", "again"), "local", "Test a pull request's last tested commit again, keeping the earlier result.",
            "It waits its turn like any other test; `title-runs run --once` starts it now. It's tested against the newest main.",
            "Your local tests list.", '{"pr", "head"}', ("title-runs local again 4287",), _pr, run_local_again),
    Command(("local", "report"), "local", "A pull request's report: the link to post it on, then its text in the project's form.",
            "The newest result's report (--test N for an earlier one), with the traces to attach. Nothing is posted for you. Post it "
            "yourself, then mark it with `title-runs local posted`. --text prints only the report, ready to paste.",
            "Nothing (makes the folder of traces to attach).",
            '{"pr", "link", "head", "at", "verdict", "stale", "posted", "text", "traces": [{"name", "path", "size", "fits", "run"}], "folder"}',
            ("title-runs local report 4287", "title-runs local report 4287 --text | wl-copy", "title-runs --json local report 4287"),
            lambda p: (_pr(p), _test(p), p.add_argument("--text", action="store_true", help="only the report's text")), run_local_report),
    Command(("local", "files"), "local", "The traces to attach to a pull request's report, and the folder they're in.",
            "Each counted run's trace, named after its run, in one folder you can drag them from into the comment under Traces. A "
            "trace over GitHub's 25 MB limit is listed but can't be attached.",
            "Makes the folder on this computer.", '{"pr", "folder", "traces": [{"name", "path", "size", "fits", "run"}]}',
            ("title-runs local files 4287",), lambda p: (_pr(p), _test(p)), run_local_files),
    Command(("local", "posted"), "local", "Mark a pull request's report as posted by you (--undo: not posted).",
            "A posted result is never marked out of date. This only records it on this computer; it doesn't post anything.",
            "Your local tests list.", '{"pr", "head", "posted"}', ("title-runs local posted 4287", "title-runs local posted 4287 --undo"),
            lambda p: (_pr(p), _test(p), p.add_argument("--undo", action="store_true", help="mark it not posted")), run_local_posted),
    Command(("local", "follow"), "local", "Also test every open pull request of these people.",
            "Every new commit they push to one of their pull requests is tested without you checking it first, so only follow "
            "people whose code you'd run.", "Your settings.", '{"people": [...]}',
            ("title-runs local follow LOGIN",), lambda p: p.add_argument("people", nargs="+", metavar="LOGIN"), run_local_follow),
    Command(("local", "unfollow"), "local", "Stop following these people; pull requests you added by number stay.", "", "Your settings.",
            '{"people": [...]}', ("title-runs local unfollow LOGIN",), lambda p: p.add_argument("people", nargs="+", metavar="LOGIN"),
            lambda ctx, args: run_local_follow(ctx, args, follow=False)),
    Command(("local", "fixes"), "local", "Show or set the pull requests merged into both builds as fixes (--none: no fixes).",
            "For when main can't run your games without them. Any that main already includes are skipped. If one doesn't merge, or "
            "its latest commit wasn't pushed by its author, local tests pause and say why.",
            "Your settings, when given.", '{"fixes": [PR, ...]}', ("title-runs local fixes", "title-runs local fixes 9730", "title-runs local fixes --none"),
            lambda p: (p.add_argument("prs", nargs="*", metavar="PR"), p.add_argument("--none", action="store_true", help="no fixes")),
            run_local_fixes),
    Command(("local", "main"), "local", "The version of main local tests are tested against (--latest: the newest, from the next test).",
            "Main stays at one version for 12 hours, so the pull requests tested together are compared with the same main, which "
            "is built and warmed up once.",
            "With --latest: your local tests list.", '{"main", "pinned": {"main", "base", "fixes", "at"} or null}',
            ("title-runs local main", "title-runs local main --latest"),
            lambda p: p.add_argument("--latest", action="store_true", help="use the newest main from the next test on"), run_local_main),
    Command(("local", "repository"), "local", "Show or set the project whose pull requests you test.", "",
            "Your settings, when given.", '{"repository"}', ("title-runs local repository", "title-runs local repository boykopovar/AnyPS5"),
            lambda p: p.add_argument("repository", nargs="?", metavar="OWNER/NAME"), run_local_repository),

    Command(("games", "list"), "games", "Your games, with each one's test, scenario and folder.", "`title-runs games` on its own does the same.",
            NOTHING, '{"games": [{"title_id", "name", "version", "test", "scenario", "scenarios", "folder"}]}', ("title-runs games",), None, run_games),
    Command(("games", "scenario"), "games", "Show or choose the scenario a game is tested in.",
            "A scenario is one specific run of a game, which may or may not load a save first (GTA V's prologue, or Franklin's house). "
            "The game's next tests run in it.",
            SETTINGS + " Only when a scenario is given.", '{"title_id", "scenario", "scenarios": [{"id", "name", "scene"}]}',
            ("title-runs games scenario PPSA04263", "title-runs games scenario PPSA04263 franklins-house"),
            lambda p: (p.add_argument("title_id", metavar="TITLE_ID"), p.add_argument("scenario", nargs="?", metavar="SCENARIO")), run_games_scenario),
    Command(("games", "record"), "games", "Record a scenario: play from a scenario's starting scene with a controller, for tests to replay.",
            "Starts the game on the main build (a local test builds it) in the scenario named by --from and goes to its starting "
            "scene on its own. Then you take over: the first second is ignored, and after that everything you do on the controller "
            "is recorded for --seconds (100 to 600; timing starts about 30 s in and lasts up to 60). The new scenario is the one "
            "you started from plus your recording, and every test in it replays the recording from the same scene. Stopping "
            "(title-runs stop, or Stop in the window) ends it without saving.",
            "Starts the game on this computer, and writes the new scenario to the state folder.",
            'one object per line: {"progress": text} as it goes, then {"recorded": ID, "path"}',
            ("title-runs games record PPSA04263 --from franklins-house --name \"Out of the house\" --scene \"Franklin walks out of his "
             "house to the road\"",),
            lambda p: (p.add_argument("title_id", metavar="TITLE_ID"),
                       p.add_argument("--from", dest="start", required=True, metavar="SCENARIO", help="the scenario to start from"),
                       p.add_argument("--name", required=True, help="the new scenario's name"),
                       p.add_argument("--scene", required=True, help="what happens in it, for reports (up to 120 characters)"),
                       p.add_argument("--seconds", type=int, default=150, help="how long to record (100 to 600, default 150)"),
                       p.add_argument("--id", help="the new scenario's id (default: from its name)")), run_games_record),
    Command(("window",), "games", "Open the window (the first-run walkthrough if the config is new).",
            changes="Nothing, until you change something in the window.", examples=("title-runs window", "title-runs window --config ~/games/anyps5.toml"),
            passthrough=window_main),

    Command(("ui",), "games", "The window, by its first name.", passthrough=window_main, hidden=True),
]

BY_NAME = {command.path: command for command in COMMANDS}
DEFAULTS = {"local": ("local", "list"), "games": ("games", "list")}


def default_config():
    return Path(os.environ.get(CONFIG_ENV) or configs.DEFAULT_CONFIG)


# -- help --------------------------------------------------------------------------------------------------------------

def overview():
    lines = ["title-runs: test AnyPS5 pull requests on your own games and hardware, against main.", "",
             "Usage: title-runs [--config FILE] [--json] COMMAND [ARGS]", ""]
    width = max(len(c.name) for c in COMMANDS if not c.hidden) + 2
    for key, heading in GROUPS.items():
        lines.append(heading)
        for c in COMMANDS:
            if c.group == key and not c.hidden:
                lines.append(f"  {c.name.ljust(width)}{c.summary}")
        lines.append("")
    lines += ["Options", f"  --config FILE   the config (default: ${CONFIG_ENV}, else anyps5-title-runs/config.toml in your config folder)",
              "  --json          print JSON: one object, or one per line for run and games record", "",
              "Exit codes: 0 done, 1 couldn't (the message says why), 2 the command was written wrong.",
              "No command posts anything or writes to GitHub. You post reports yourself.",
              "`title-runs help COMMAND` says more about each."]
    return "\n".join(lines)


def group_help(name):
    """`title-runs local --help`: the group's commands."""
    commands = [c for c in COMMANDS if c.path[0] == name and len(c.path) == 2]
    width = max(len(c.name) for c in commands) + 2
    lines = [f"Usage: title-runs {name} COMMAND [ARGS]   (title-runs {name} alone is title-runs {' '.join(DEFAULTS[name])})", ""]
    lines += [f"  {c.name.ljust(width)}{c.summary}" for c in commands]
    return "\n".join(lines + ["", f"`title-runs help {name} COMMAND` says more about each."])


def command_help(command):
    if command.passthrough:
        out = io.StringIO()
        with redirect_stdout(out):
            try:
                command.passthrough(["--help"])
            except SystemExit:
                pass
        body = out.getvalue().rstrip()
    else:
        body = build_parser(command.path).format_help().rstrip()
    lines = [body, ""]
    if command.changes:
        lines.append(f"Changes: {command.changes}")
    if command.json:
        lines.append(f"JSON (--json): {command.json}")
    if command.examples:
        lines += ["", "Examples:"] + [f"  {e}" for e in command.examples]
    return "\n".join(lines)


def markdown():
    """docs/CLI.md: the overview and every command's help, as the command line prints them."""
    lines = ["# The title-runs command line", "",
             "Made by `title-runs help --markdown` from the commands themselves (title_runs/cli.py); a test checks it is current.", "",
             "```", overview(), "```", ""]
    for key, heading in GROUPS.items():
        lines += [f"## {heading}", ""]
        for c in COMMANDS:
            if c.group == key and not c.hidden:
                lines += [f"### `title-runs {c.name}`", "", c.summary, "", "```", command_help(c), "```", ""]
    return "\n".join(lines).rstrip() + "\n"


# -- the parser ----------------------------------------------------------------------------------------------------------

class Parser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        self.exit(EXIT_USAGE, f"{self.prog}: {message} (title-runs help says more)\n")


def wrap(text):
    return "\n\n".join(textwrap.fill(part, 100) for part in text.split("\n\n"))


def build_parser(path=None):
    """The whole parser, or (path) the parser of one command, for its help."""
    root = Parser(prog="title-runs", add_help=False)
    root.add_argument("--config", type=Path, default=default_config())
    root.add_argument("--json", action="store_true")
    sub = root.add_subparsers(dest="command", metavar="COMMAND", parser_class=Parser)
    groups = {}
    for command in COMMANDS:
        if command.passthrough:
            continue
        options = {"description": wrap(command.summary + ("\n\n" + command.description if command.description else "")),
                   "formatter_class": argparse.RawDescriptionHelpFormatter, "prog": f"title-runs {command.name}"}
        if len(command.path) == 1:
            parser = sub.add_parser(command.path[0], **options)
        else:
            if command.path[0] not in groups:
                group = sub.add_parser(command.path[0], prog=f"title-runs {command.path[0]}")
                groups[command.path[0]] = group.add_subparsers(dest="sub", metavar="COMMAND", parser_class=Parser)
            parser = groups[command.path[0]].add_parser(command.path[1], **options)
        if command.arguments:
            command.arguments(parser)
        parser.set_defaults(command_path=command.path)
        if path == command.path:
            return parser
    return root


# -- main ------------------------------------------------------------------------------------------------------------------

def find(words):
    """The command words name, with a group's default for a group alone ("local" is "local list"), or None."""
    if tuple(words[:2]) in BY_NAME:
        return BY_NAME[tuple(words[:2])]
    if words[:1] and words[0] in DEFAULTS and (len(words) == 1 or words[1].startswith("-")):
        return BY_NAME[DEFAULTS[words[0]]]
    return BY_NAME.get(tuple(words[:1]))


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    options, rest = [], list(argv)
    while rest and rest[0] in ("--json", "--config"):  # the options before the command
        options.append(rest.pop(0))
        if options[-1] == "--config" and rest:
            options.append(rest.pop(0))
    if not rest or rest[0] in ("-h", "--help"):
        print(overview())
        return EXIT_OK
    if rest[0] == "help":
        if "--markdown" in rest:
            print(markdown(), end="")
            return EXIT_OK
        words = rest[1:]
        if not words:
            print(overview())
            return EXIT_OK
        if words[0] in DEFAULTS and len(words) == 1:
            print(group_help(words[0]))
            return EXIT_OK
        command = find(words)
        if command is None:
            print(f"title-runs: there is no command {' '.join(words)!r}.\n\n{overview()}", file=sys.stderr)
            return EXIT_USAGE
        print(command_help(command))
        return EXIT_OK
    if rest[0] in DEFAULTS and rest[1:2] in (["-h"], ["--help"]):
        print(group_help(rest[0]))
        return EXIT_OK
    command = find(rest)
    if command is not None and command.passthrough:
        config = options[options.index("--config") + 1:][:1] if "--config" in options else []
        extra = ["--config", config[0]] if config and command.path in (("window",), ("ui",)) else []
        return command.passthrough(extra + rest[1:]) or EXIT_OK
    if command is not None and ("-h" in rest or "--help" in rest):
        print(command_help(command))
        return EXIT_OK
    if command is not None and command.path in DEFAULTS.values() and tuple(rest[:2]) != command.path:
        rest = list(command.path) + rest[1:]
    try:
        args = build_parser().parse_args(options + rest)
    except SystemExit as error:  # the command was written wrong: argparse has said how
        return error.code if isinstance(error.code, int) else EXIT_USAGE
    if not getattr(args, "command_path", None):
        print(overview())
        return EXIT_USAGE
    command = BY_NAME[args.command_path]

    def echo(text, data=None):
        print(json.dumps(data if data is not None else {"log": text}, default=str) if args.json else text, flush=True)
    try:
        out = command.run(Context(args, echo), args)
    except Failed as error:
        if args.json:
            print(json.dumps({"error": str(error)}))
        else:
            print(f"title-runs: {error}", file=sys.stderr)
        return EXIT_FAILED
    if args.json:
        streamed = command.path in (("run",), ("games", "record"))
        print(json.dumps(out.data, default=str) if streamed else json.dumps(out.data, indent=2, default=str))
    elif out.text:
        print("\n".join(out.text) if isinstance(out.text, list) else out.text)
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
