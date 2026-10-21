"""The relay workflow's step (results_repo/.github/workflows/relay.yml):

  title-runs relay poll --state DIR [--anyps5-git DIR --anyps5-remote origin --main-ref origin/main]

--state is the results repository's checkout (config.json names AnyPS5 and the results repository). AnyPS5 is read
and written as the App with the installation token in $TITLE_RUNS_APP_TOKEN; the results repository with the
workflow's own $GITHUB_TOKEN. --fake FILE[:OUTBOX] uses the stand-in (gh.FakeGitHub) instead. The step after this
one commits the checkout. Runs from the tool's own checkout at a pinned commit, never from the results repository.

--dry-run OUTBOX reads the real repositories (any read token in the two variables, e.g. `gh auth token`) and records
every write in OUTBOX instead of making it (gh.DryRun); --results-absent when the results repository does not exist
yet. Use it on a copy of the state: the state files are written as if the writes had happened.
"""

import argparse
import json
import sys
from pathlib import Path

from . import relay
from .. import gh


def repos(config, fake, dry_run=None, results_absent=False):
    if dry_run:
        anyps5 = gh.DryRun(gh.GitHubRepo(config["repository"], token_env="TITLE_RUNS_APP_TOKEN"), dry_run, config.get("app", {}).get("bot") or "title-runs[bot]")
        inner = None if results_absent else gh.GitHubRepo(config["results_repository"], token_env="GITHUB_TOKEN")
        return anyps5, gh.DryRun(inner, dry_run, "github-actions[bot]", config["results_repository"])
    if fake:
        path, _, outbox = fake.partition(":")
        github = gh.FakeGitHub(path, outbox or None)
        return github.as_(config["repository"], identity="title-runs[bot]"), github.as_(config["results_repository"], identity="github-actions[bot]")
    return gh.GitHubRepo(config["repository"], token_env="TITLE_RUNS_APP_TOKEN"), gh.GitHubRepo(config["results_repository"], token_env="GITHUB_TOKEN")


def main(argv=None):
    parser = argparse.ArgumentParser(prog="title-runs relay")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("poll")
    p.add_argument("--state", type=Path, required=True)
    p.add_argument("--anyps5-git", type=Path)
    p.add_argument("--anyps5-remote")
    p.add_argument("--main-ref", default="origin/main")
    p.add_argument("--fake")
    p.add_argument("--dry-run", type=Path, metavar="OUTBOX")
    p.add_argument("--results-absent", action="store_true")
    args = parser.parse_args(argv)
    config = json.loads((args.state / "config.json").read_text())
    anyps5, results = repos(config, args.fake, args.dry_run, args.results_absent)
    changed = relay.Relay(args.state, anyps5, results, args.anyps5_git, args.anyps5_remote, args.main_ref).run()
    print(f"relay: changed {', '.join(f'#{n}' for n in changed) or 'nothing'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
