"""title-runs: the command line.

  title-runs [--config FILE] poll [--fixture LISTING.json] [--at ISO-TIME]
  title-runs status
  title-runs confirm PR [HEAD]
  title-runs run [--pr PR] [--post]      run the ready jobs (or one PR's ready head), render, post (dry-run unless --post
                                         and poster.enabled)
  title-runs render PR [--results FILE]  print the comment the last results (or FILE) give
  title-runs publish PR --results FILE   mark the PR's current head done with FILE's results, render and post (dry-run);
                                         for results made elsewhere, and for the simulated head of the README's demo
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

from . import ROOT, config as configs, job, poller, poster, report
from .github import GraphQL
from .state import DONE, FAILED, READY, RUNNING, State, now, parse


def paths(config):
    state_dir = config.state_dir
    return state_dir, State(state_dir / "state.json"), poller.Listing(state_dir / "cache" / "pull-requests.json")


def notes(config):
    data = __import__("tomllib").loads(config.path.read_text())
    return data.get("report", {}).get("notes", [])


def cmd_poll(config, args):
    state_dir, state, listing = paths(config)
    if args.fixture:
        listing.merge(json.loads(Path(args.fixture).read_text())["nodes"])
        listing.save()
        print(f"listing: merged {args.fixture}")
    else:
        client = GraphQL(config.github_client, config.github_token_env, config.budget_reserve)
        pages = listing.refresh(client, config.owner, config.name)
        listing.fetch(client, config.owner, config.name, config.follow_prs)
        print(f"listing: {pages} page(s), {len(listing.open())} open PRs cached; GraphQL cost {client.spent}, remaining {client.remaining}")
    moment = parse(args.at) if args.at else now()
    events = poller.update(state, listing, config, moment)
    state.save()
    for number, kind, detail in events:
        print(f"#{number}: {kind} {detail}")
    if not events:
        print("no change")
    return 0


def cmd_status(config, args):
    _, state, _ = paths(config)
    for number, entry in sorted(state.prs().items()):
        current = state.current(number)
        print(f"#{number} {entry.get('title', '')[:60]} (followed: {entry.get('followed')}; author {entry.get('author')})")
        for head in entry["heads"]:
            print(f"    {head['head'][:9]} {head['status']:10s} seen {head['seen']} {head.get('trust', '')}")
        if entry.get("comment_id"):
            print(f"    comment {entry['comment_id']}, {len(entry.get('comment_posts', []))} post(s)")
    return 0


def cmd_confirm(config, args):
    _, state, _ = paths(config)
    head = poller.confirm(state, args.pr, args.head)
    state.save()
    print(f"#{args.pr} {head['head'][:9]}: {head['status']}")
    return 0


def publish(config, state, number, results, post_real):
    entry = state.pr(number)
    history = entry.setdefault("history", [])
    summary = report.head_summary(results)
    previous = history[-1] if history else None
    action, reason = report.decide(previous, summary, bool(entry.get("comment_id")))
    body = report.render(config, number, results, history, notes(config))
    history.append(summary)
    record = poster.post(config, state, number, body, action, reason, dry_run=not post_real)
    print(f"#{number}: {record['action']} comment ({reason}); {'posted ' + str(record.get('url')) if not record['dry_run'] else 'dry run: ' + record['body_file']}")
    return record


def cmd_run(config, args):
    state_dir, state, _ = paths(config)
    todo = [(n, h) for n, h in poller.ready(state) if args.pr is None or n == args.pr]
    if not todo:
        print("no ready job")
        return 0
    for number, head in todo:
        head["status"] = RUNNING
        state.save()
        print(f"#{number}: running {head['head'][:9]}")
        results = job.run(config, state_dir, number, head["head"], lambda text: print(f"  {text}", flush=True))
        poller.finish(state, number, head["head"], DONE if results["status"] == "done" else FAILED, state_dir / "jobs" / results["job"])
        publish(config, state, number, results, args.post)
        state.save()
    return 0


def cmd_render(config, args):
    state_dir, state, _ = paths(config)
    entry = state.pr(args.pr)
    if args.results:
        results = json.loads(Path(args.results).read_text())
    else:
        head = state.current(args.pr)
        job_dir = Path(head["job"]) if head.get("job") else state_dir / "jobs" / f"{args.pr}-{head['head'][:12]}"
        results = json.loads((job_dir / "results.json").read_text())
    history = [h for h in entry.get("history", []) if h["head"] != results["head"]]
    print(report.render(config, args.pr, results, history, notes(config)))
    return 0


def cmd_publish(config, args):
    state_dir, state, _ = paths(config)
    results = json.loads(Path(args.results).read_text())
    head = state.current(args.pr)
    if head is None or head["head"] != results["head"]:
        raise SystemExit(f"#{args.pr}: the current head is {head and head['head'][:9]}, the results are for {results['head'][:9]}")
    if head["status"] not in (READY, RUNNING):
        raise SystemExit(f"#{args.pr} {head['head'][:9]} is {head['status']} ({head.get('trust', '')}); only a ready head's results are published")
    poller.finish(state, args.pr, results["head"], DONE if results.get("status") == "done" else FAILED, args.results)
    publish(config, state, args.pr, results, args.post)
    state.save()
    return 0


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
    parser = argparse.ArgumentParser(prog="title-runs", description="Title runs of followed AnyPS5 pull requests.")
    parser.add_argument("--config", type=Path, default=ROOT / "config.toml")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("poll")
    p.add_argument("--fixture", type=Path)
    p.add_argument("--at")
    sub.add_parser("status")
    p = sub.add_parser("confirm")
    p.add_argument("pr", type=int)
    p.add_argument("head", nargs="?")
    p = sub.add_parser("run")
    p.add_argument("--pr", type=int)
    p.add_argument("--post", action="store_true", help="post for real (also needs poster.enabled = true)")
    p = sub.add_parser("render")
    p.add_argument("pr", type=int)
    p.add_argument("--results", type=Path)
    p = sub.add_parser("publish")
    p.add_argument("pr", type=int)
    p.add_argument("--results", type=Path, required=True)
    p.add_argument("--post", action="store_true")
    args = parser.parse_args(argv)
    config = configs.load(args.config)
    return {"poll": cmd_poll, "status": cmd_status, "confirm": cmd_confirm, "run": cmd_run, "render": cmd_render, "publish": cmd_publish}[args.command](config, args)


if __name__ == "__main__":
    sys.exit(main())
