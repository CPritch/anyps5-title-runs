"""The relay workflow's step (results_repo/.github/workflows/relay.yml):

  title-runs relay poll --state DIR [--anyps5-git DIR --anyps5-remote origin --main-ref origin/main]

--state is the results repository's checkout (config.json names AnyPS5 and the results repository). AnyPS5 is read
and written as the App with the installation token in $TITLE_RUNS_APP_TOKEN; the results repository with the
workflow's own $GITHUB_TOKEN. --fake FILE[:OUTBOX] uses the stand-in (gh.FakeGitHub) instead. The step after this
one commits the checkout. Runs from the tool's own checkout at a pinned commit, never from the results repository.
"""

import argparse
import json
import sys
from pathlib import Path

from . import relay
from .. import gh


def repos(config, fake):
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
    args = parser.parse_args(argv)
    config = json.loads((args.state / "config.json").read_text())
    anyps5, results = repos(config, args.fake)
    changed = relay.Relay(args.state, anyps5, results, args.anyps5_git, args.anyps5_remote, args.main_ref).run()
    print(f"relay: changed {', '.join(f'#{n}' for n in changed) or 'nothing'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
