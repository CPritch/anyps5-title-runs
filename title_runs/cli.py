"""title-runs: the command line.

  title-runs [--config FILE] poll [--fixture LISTING.json] [--at ISO-TIME]
  title-runs status
  title-runs confirm PR [HEAD]
  title-runs run [--pr PR] [--post]      run the ready jobs (or one PR's ready head), render, post (dry-run unless --post
                                         and poster.enabled)
  title-runs render PR [--results FILE]  print the comment the last results (or FILE) give
  title-runs publish PR --results FILE   mark the PR's current head done with FILE's results, render and post (dry-run);
                                         for results made elsewhere, and for the simulated head of the README's demo
  title-runs relay queue|publish ...     the results repository's workflows (title_runs/relay/__main__.py)
  title-runs export-results-repo MAIN STATE [OWNER/NAME]   fill a results repository's two branches from results_repo/
  title-runs standin hook|label|command|push|refresh --root DIR ...   the local stand-in for GitHub (standin.py)
  title-runs client [--config FILE] queue|next|run-once|daemon       the tester's client without the window
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
        poller.finish(state, number, head["head"], DONE if results["status"] == "done" else FAILED, state_dir / "jobs" / f"{number}-{head['head'][:12]}")
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
        results = json.loads((state_dir / "jobs" / f"{args.pr}-{head['head'][:12]}" / "results.json").read_text())
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
    """title-runs standin hook|label|command|push|refresh --root DIR ...: the local stand-in (title_runs/standin.py)."""
    from . import standin
    parser = argparse.ArgumentParser(prog="title-runs standin")
    sub = parser.add_subparsers(dest="what", required=True)
    for name in ("hook", "label", "command", "push", "refresh"):
        p = sub.add_parser(name)
        p.add_argument("--root", type=Path, required=True)
        if name == "hook":
            p.add_argument("--before", required=True)
            p.add_argument("--after", required=True)
            p.add_argument("--actor", required=True)
        if name in ("label", "command", "push"):
            p.add_argument("pr", type=int)
            p.add_argument("--by", required=True)
        if name == "command":
            p.add_argument("body")
            p.add_argument("--association", default="OWNER")
        if name == "push":
            p.add_argument("head")
    args = parser.parse_args(argv)
    stand = standin.Standin(args.root)
    if args.what == "hook":
        report = stand.run_publish(args.actor, args.before, args.after)
        print(json.dumps(report))
        return 1 if report["refused"] else 0
    if args.what == "label":
        changed = stand.label(args.pr, args.by)
    elif args.what == "command":
        changed = stand.command(args.pr, args.body, args.by, args.association)
    elif args.what == "push":
        changed = stand.push(args.pr, args.head, args.by)
    else:
        changed = stand.run_queue("schedule", refresh=True)
    print(f"queue workflow: changed {', '.join(f'#{n}' for n in changed) or 'nothing'}")
    return 0


def client_command(argv):
    """title-runs [--config FILE] client queue|next|run-once|daemon: the tester's client without the window."""
    from . import client
    parser = argparse.ArgumentParser(prog="title-runs client")
    parser.add_argument("--config", type=Path, default=ROOT / "config.toml")
    parser.add_argument("what", choices=("queue", "next", "run-once", "daemon"))
    parser.add_argument("--ignore-schedule", action="store_true", help="run-once: start even if the schedule says not now")
    args = parser.parse_args(argv)
    engine = client.Client(configs.load(args.config), log=lambda text: print(text, flush=True))
    if args.what == "queue":
        for choice in engine.ranked():
            print(f"{choice.score:6.2f}  #{choice.entry['pr']} {choice.entry['head'][:9]} {choice.entry['priority']:6s}  " + "; ".join(choice.reasons))
        return 0
    if args.what == "next":
        best = engine.next_job()
        print(f"#{best.entry['pr']} {best.entry['head'][:9]} ({best.score:.2f})" if best else "nothing to do")
        return 0
    if args.what == "daemon":
        engine.daemon()
        return 0
    if not args.ignore_schedule:
        print(engine.run_next())
        return 0
    best = engine.next_job()
    if best is None:
        print("nothing to do")
        return 0
    engine.run(best.entry["pr"], best.entry["head"], "queue", best.entry.get("title", ""), best.entry.get("author", ""))
    return 0


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["relay"]:
        from .relay.__main__ import main as relay
        return relay(argv[1:])
    if argv[:1] == ["standin"]:
        return standin_command(argv[1:])
    if argv[:1] == ["client"]:
        return client_command(argv[1:])
    if argv[:1] == ["export-results-repo"]:
        from . import export
        if len(argv) not in (3, 4):
            raise SystemExit("usage: title-runs export-results-repo MAIN_DIR STATE_DIR [OWNER/NAME]")
        main_dir, state_dir = export.export(argv[1], argv[2], argv[3] if len(argv) == 4 else None)
        print(f"results repository: main in {main_dir}, state in {state_dir}")
        return 0
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
