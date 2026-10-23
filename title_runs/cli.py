"""title-runs: the command line.

  title-runs relay poll ...              the results repository's workflow (title_runs/relay/__main__.py)
  title-runs export-results-repo DIR [OWNER/ANYPS5 OWNER/RESULTS] [--app app.json --git ...]   a results repository from results_repo/
  title-runs app manifest|create --results-repo DIR [--out DIR]   the GitHub App, from a manifest (title_runs/app.py)
  title-runs standin tick|label|unlabel|command|push|approve|decline|codes|authorize --root DIR ...   the local stand-in
  title-runs client [--config FILE] status|sign-in|register|use REPO|queue|next|run-once|daemon   the tester's client without the window
  title-runs ui [--config FILE] [--setup] [--screenshots DIR] ...     the tray and the window (title_runs/ui/app.py)
"""

import argparse
import json
import sys
from pathlib import Path

from . import config as configs


def standin_command(argv):
    """title-runs standin tick|label|unlabel|command|push|approve|decline|codes|authorize --root DIR ...: the local
    stand-in for GitHub and the results repository (title_runs/standin.py)."""
    from . import standin
    parser = argparse.ArgumentParser(prog="title-runs standin")
    sub = parser.add_subparsers(dest="what", required=True)
    for name in ("tick", "label", "unlabel", "command", "push", "approve", "decline", "codes", "authorize"):
        p = sub.add_parser(name)
        p.add_argument("--root", type=Path, required=True)
        if name in ("label", "unlabel", "command", "push"):
            p.add_argument("pr", type=int)
        if name in ("approve", "decline"):
            p.add_argument("issue", type=int)
        if name in ("label", "unlabel", "command", "push", "approve", "decline"):
            p.add_argument("--by", required=True)
        if name == "command":
            p.add_argument("body")
        if name == "push":
            p.add_argument("head")
        if name == "authorize":
            p.add_argument("code")
            p.add_argument("--as", dest="login", required=True)
    args = parser.parse_args(argv)
    stand = standin.Standin(args.root)
    if args.what == "tick":
        changed = stand.tick()
        print(f"relay: changed {', '.join(f'#{n}' for n in changed) or 'nothing'}")
    elif args.what == "codes":
        for code in stand.codes():
            print(code)
    elif args.what == "authorize":
        stand.authorize(args.code, args.login)
    elif args.what in ("approve", "decline"):
        getattr(stand, args.what)(args.issue, args.by)
    elif args.what == "command":
        stand.command(args.pr, args.body, args.by)
    elif args.what == "push":
        stand.push(args.pr, args.head, args.by)
    else:
        getattr(stand, args.what)(args.pr, args.by)
    return 0


def client_command(argv):
    """title-runs client [--config FILE] queue|next|run-once|daemon|status|sign-in|register|use OWNER/NAME: the tester's
    client without the window."""
    from . import client
    parser = argparse.ArgumentParser(prog="title-runs client")
    parser.add_argument("--config", type=Path, default=configs.DEFAULT_CONFIG)
    parser.add_argument("what", choices=("queue", "next", "run-once", "daemon", "status", "sign-in", "register", "use"))
    parser.add_argument("location", nargs="?", help="use: the results repository, OWNER/NAME or a URL (a path for the stand-in)")
    parser.add_argument("--ignore-schedule", action="store_true", help="run-once: start even if the schedule says not now (still needs ready)")
    args = parser.parse_args(argv)
    engine = client.Client(configs.load(args.config), log=lambda text: print(text, flush=True))
    if args.what == "use":
        if not args.location:
            parser.error("use needs OWNER/NAME or a URL")
        from . import configfile
        engine.use(args.location)
        configfile.save(engine.config)
        state, _ = engine.registration()
        print(f"results repository {engine.results_repository()} ({engine.config.results_url}); "
              f"{'signed in as ' + engine.tester() if engine.tester() else 'sign in again (title-runs client sign-in)'}; machine {state}")
        return 0
    engine.repo.sync()
    if args.what == "status":
        ready, why = engine.ready()
        state, record = engine.registration()
        print(f"signed in as {engine.tester() or '-'}; machine {engine.config.machine}: {state}; {'ready' if ready else 'not ready: ' + why}")
        return 0
    if args.what == "sign-in":
        flow = engine.flow()
        device = flow.start()
        print(f"Open {device['verification_uri']} and enter {device['user_code']}", flush=True)
        print(f"signed in as {flow.wait(device)['login']}")
        return 0
    if args.what == "register":
        print(f"registration issue #{engine.register()}")
        return 0
    if args.what == "queue":
        for choice in engine.ranked(sync=False):
            print(f"{choice.score:6.2f}  #{choice.entry['pr']} {choice.entry['head'][:9]} {choice.entry['priority']:6s}  " + "; ".join(choice.reasons))
        return 0
    if args.what == "next":
        best = engine.next_job(sync=False)
        print(f"#{best.entry['pr']} {best.entry['head'][:9]} ({best.score:.2f})" if best else "nothing to do")
        return 0
    if args.what == "daemon":
        engine.daemon()
        return 0
    if not args.ignore_schedule:
        print(engine.run_next())
        return 0
    ready, why = engine.ready()
    if not ready:
        print(f"not ready: {why}")
        return 1
    best = engine.next_job(sync=False)
    if best is None:
        print("nothing to do")
        return 0
    engine.run(best.entry["pr"], best.entry["head"], "queue", best.entry.get("title", ""), best.entry.get("author", ""))
    return 0


def export_command(argv):
    """title-runs export-results-repo DIR [OWNER/ANYPS5 OWNER/RESULTS] [--maintainers A,B] [--app app.json]
    [--tool OWNER/NAME] [--tool-commit SHA] [--git]: a results repository, ready to push with --git."""
    from . import export
    parser = argparse.ArgumentParser(prog="title-runs export-results-repo")
    parser.add_argument("dir", type=Path)
    parser.add_argument("anyps5", nargs="?")
    parser.add_argument("results", nargs="?")
    parser.add_argument("--maintainers", help="comma-separated logins")
    parser.add_argument("--app", type=Path, help="app.json from 'title-runs app create'")
    parser.add_argument("--tool", help="this tool's repository, OWNER/NAME")
    parser.add_argument("--tool-commit", help="the commit the workflow runs (default: this checkout's HEAD, which must be pushed)")
    parser.add_argument("--git", action="store_true", help="make DIR a git repository with one commit, ready to push")
    args = parser.parse_args(argv)
    app = None
    if args.app:
        record = json.loads(args.app.read_text())
        app = {"id": record["id"], "client_id": record["client_id"], "bot": record["bot"]}
    tool = None
    if args.tool or args.tool_commit:
        tool = {"repository": args.tool or "CPritch/anyps5-title-runs", "commit": args.tool_commit or export.head_commit()}
    dest = export.export(args.dir, args.anyps5, args.results, args.maintainers.split(",") if args.maintainers else None, app, tool)
    if args.git:
        export.commit(dest)
    print(f"results repository in {dest}" + (" (a git repository with one commit; push it to the new repository)" if args.git else ""))
    return 0


def app_command(argv):
    """title-runs app manifest|create --results-repo DIR [--name title-runs-dev] [--out DIR]: the GitHub App, from a
    manifest (title_runs/app.py). AnyPS5, the results repository and this tool come from DIR's config.json."""
    from . import app
    parser = argparse.ArgumentParser(prog="title-runs app")
    parser.add_argument("what", choices=("manifest", "create"))
    parser.add_argument("--results-repo", type=Path, required=True, help="the exported results repository (its config.json)")
    parser.add_argument("--name", default="title-runs-dev")
    parser.add_argument("--out", type=Path, help="create: where app.json and the private key go (keep it out of every repository)")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args(argv)
    config = json.loads((args.results_repo / "config.json").read_text())
    names = (config["repository"], config["results_repository"], config["tool"]["repository"])
    if args.what == "manifest":
        print(json.dumps(app.manifest(args.name, *names), indent=2))
        return 0
    if not args.out:
        parser.error("create needs --out")
    app.create(args.out, args.name, *names, port=args.port, results_repo=args.results_repo, open_browser=not args.no_browser)
    return 0


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["relay"]:
        from .relay.__main__ import main as relay
        return relay(argv[1:])
    if argv[:1] == ["ui"]:
        from .ui.app import main as ui
        return ui(argv[1:])
    if argv[:1] == ["standin"]:
        return standin_command(argv[1:])
    if argv[:1] == ["client"]:
        return client_command(argv[1:])
    if argv[:1] == ["export-results-repo"]:
        return export_command(argv[1:])
    if argv[:1] == ["app"]:
        return app_command(argv[1:])
    print(__doc__.strip())
    return 0 if argv[:1] in ([], ["help"], ["-h"], ["--help"]) else 2


if __name__ == "__main__":
    sys.exit(main())
