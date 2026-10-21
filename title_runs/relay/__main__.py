"""The workflows' steps (results_repo/.github/workflows/):

  title-runs relay queue --state DIR --data DIR --event-name NAME --event-file FILE [--anyps5-git DIR ...]
  title-runs relay publish --state DIR --data DIR --actor LOGIN --before SHA --after SHA

--state is a checkout of the results repository's state branch, --data of its main branch. The workflows run this
from a checkout of the tool repository at a pinned commit, never from the results repository, which testers write to.

--forge github (the default) calls GitHub with the App's token in $TITLE_RUNS_APP_TOKEN; --forge fake:STATE:OUTBOX
uses the stand-in (relay/forge.py's FakeForge). The step after this one commits queue.json and comments.json.
publish exits 1 when it refused anything, so the run shows red to the maintainers.
"""

import argparse
import json
import sys
from pathlib import Path

from . import forge as forges, publish, queue


def make_forge(spec, repository):
    if spec == "github":
        return forges.GitHubForge(repository)
    kind, state, outbox = spec.split(":", 2)
    if kind != "fake":
        raise SystemExit(f"--forge {spec}: github or fake:STATE:OUTBOX")
    return forges.FakeForge(state, outbox)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="relay")
    sub = parser.add_subparsers(dest="command", required=True)
    q = sub.add_parser("queue")
    q.add_argument("--state", type=Path, required=True)
    q.add_argument("--data", type=Path, required=True)
    q.add_argument("--event-name", required=True)
    q.add_argument("--event-file", type=Path)
    q.add_argument("--forge", default="github")
    q.add_argument("--anyps5-git", type=Path)
    q.add_argument("--anyps5-remote")
    q.add_argument("--main-ref", default="origin/main")
    p = sub.add_parser("publish")
    p.add_argument("--state", type=Path, required=True)
    p.add_argument("--data", type=Path, required=True)
    p.add_argument("--actor", required=True)
    p.add_argument("--before", default="")
    p.add_argument("--after", required=True)
    p.add_argument("--forge", default="github")
    args = parser.parse_args(argv)
    repository = json.loads((args.state / "config.json").read_text())["repository"]
    forge = make_forge(args.forge, repository)
    if args.command == "queue":
        workflow = queue.QueueWorkflow(args.state, args.data, forge, args.anyps5_git, args.anyps5_remote, args.main_ref)
        name, payload = args.event_name, json.loads(args.event_file.read_text()) if args.event_file else {}
        if name == "repository_dispatch":
            name, payload = payload["client_payload"]["event"], payload["client_payload"]["payload"]
        if name in ("schedule", "workflow_dispatch"):
            workflow.refresh()
        else:
            workflow.handle(name, payload)
        changed = workflow.finish()
        print(f"queue: {len(workflow.queue['entries'])} entries; changed {', '.join(f'#{n}' for n in changed) or 'nothing'}")
        return 0
    report = publish.publish(args.state, args.data, forge, args.actor, args.before, args.after)
    print(json.dumps(report, indent=1))
    return 1 if report["refused"] else 0


if __name__ == "__main__":
    sys.exit(main())
