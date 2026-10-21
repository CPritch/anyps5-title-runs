"""A local stand-in for GitHub, the public results repository and its relay workflow, until the App exists.

    root/github.json   the fake GitHub (gh.FakeGitHub): AnyPS5's pull requests, labels, comments and workflow runs; the
                       results repository's issues and comments; accounts and permissions; the device flow
    root/outbox/       every write anyone makes, with who made it (the App, the workflow, testers, maintainers)
    root/results.git   the results repository (bare): the workflow commits its state here, clients clone it
    root/anyps5.git    a stand-in AnyPS5 remote for clients and the workflow: main and the PRs' heads (objects borrowed
                       from a local clone)
    root/relay.log     what each run of the workflow did

tick() is one scheduled run of the workflow. label(), unlabel(), command() and push() act on AnyPS5 as people would; a
push also records the workflow run it would start (its time and pusher). approve() and decline() are a maintainer's
label on a registration issue; authorize() is a tester typing the device code.
"""

import datetime
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from . import export, formats, gh
from .relay import relay

ANYPS5, RESULTS = "CPritch/AnyPS5", "CPritch/anyps5-title-runs-results"
APP_BOT, WORKFLOW_BOT = "title-runs-dev[bot]", "github-actions[bot]"


def clean_env(extra=None):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(extra or {})
    return env


def git(directory, *args, env=None):
    result = subprocess.run(["git", "-C", str(directory), *args], capture_output=True, text=True, env=clean_env(env))
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args[:3])} in {directory}: {result.stderr.strip()[:300]}")
    return result.stdout.strip()


BOT = {"GIT_AUTHOR_NAME": WORKFLOW_BOT, "GIT_AUTHOR_EMAIL": "bot@localhost", "GIT_COMMITTER_NAME": WORKFLOW_BOT, "GIT_COMMITTER_EMAIL": "bot@localhost"}


def ago(minutes):
    return formats.iso(formats.now() - datetime.timedelta(minutes=minutes))


def create(root, maintainers, clone, main, pulls, permissions, tool_commit="", client_id="Iv1.standin", results=None):
    """pulls: [{"number", "title", "author", "head", "head_ref"}]; clone: a local AnyPS5 clone with main and the heads;
    permissions: {login: admin|write|read} on AnyPS5 (maintainers are also admins of the results repository)."""
    root = Path(root)
    if (root / "results.git").exists():
        raise SystemExit(f"{root} already holds a stand-in")
    root.mkdir(parents=True, exist_ok=True)
    fake = gh.FakeGitHub.create(root / "github.json", root / "outbox")
    anyps5 = fake.repo(ANYPS5)
    for pull in pulls:
        anyps5["pulls"][str(pull["number"])] = {**pull, "state": "open", "commits": [pull["head"]], "labels": []}
        anyps5["runs"].append({"head_sha": pull["head"], "created_at": ago(60), "actor": pull["author"], "event": "pull_request",
                               "branch": pull["head_ref"]})
    anyps5["permissions"].update(permissions)
    fake.repo(results or RESULTS)["permissions"].update({m: "admin" for m in maintainers})
    fake.save()
    with tempfile.TemporaryDirectory() as work:
        checkout = Path(work) / "results"
        export.export(checkout, ANYPS5, results or RESULTS, list(maintainers), {"id": 0, "client_id": client_id, "bot": APP_BOT},
                      {"repository": "CPritch/anyps5-title-runs", "commit": tool_commit})
        git(root, "init", "-q", "--bare", "-b", "main", "results.git")
        git(work, "init", "-q", "-b", "main", str(checkout))
        git(checkout, "add", "-A")
        git(checkout, "commit", "-qm", "results repository", env=BOT)
        git(checkout, "push", "-q", str(root / "results.git"), "HEAD:main")
    git(root, "init", "-q", "--bare", "-b", "main", "anyps5.git")
    objects = Path(git(clone, "rev-parse", "--path-format=absolute", "--git-common-dir")) / "objects"
    (root / "anyps5.git" / "objects" / "info" / "alternates").write_text(f"{objects}\n")
    git(root / "anyps5.git", "update-ref", "refs/heads/main", main)
    for pull in pulls:
        git(root / "anyps5.git", "update-ref", f"refs/pull/{pull['number']}/head", pull["head"])
    return Standin(root)


class Standin:
    def __init__(self, root):
        self.root = Path(root)
        self.results_git, self.anyps5_git = self.root / "results.git", self.root / "anyps5.git"
        self.endpoint = f"standin:{self.root / 'github.json'}"
        self.results_name = json.loads(git(self.root, "--git-dir", str(self.results_git), "show", "main:config.json")).get("results_repository", RESULTS)

    def github(self):
        return gh.FakeGitHub(self.root / "github.json", self.root / "outbox")

    def log(self, text):
        with open(self.root / "relay.log", "a") as stream:
            stream.write(f"{formats.iso(formats.now())} {text}\n")

    # -- the workflow --------------------------------------------------------------------------------------------------

    def tick(self):
        """One run of the relay workflow, committed to results.git as the workflow's bot."""
        work = Path(tempfile.mkdtemp(dir=self.root, prefix="run-"))
        try:
            git(work, "clone", "-q", str(self.results_git), "state")
            state = work / "state"
            fake = self.github()
            run = relay.Relay(state, fake.as_(ANYPS5, identity=APP_BOT), fake.as_(self.results_name, identity=WORKFLOW_BOT), self.anyps5_git, None, "main",
                              log=lambda text: self.log(f"relay: {text}"))
            changed = run.run()
            git(state, "add", "-A")
            if git(state, "status", "--porcelain"):
                git(state, "commit", "-qm", f"relay: {formats.iso(formats.now())}", env=BOT)
                git(state, "push", "-q", "origin", "HEAD:main")
            self.log(f"relay: run done, changed {', '.join(f'#{n}' for n in changed) or 'nothing'}")
            return changed
        finally:
            shutil.rmtree(work, ignore_errors=True)

    # -- people on AnyPS5 ------------------------------------------------------------------------------------------------

    def label(self, number, by, name="title-test"):
        self.github().as_(ANYPS5, by).add_labels(number, [name])
        self.log(f"event: {by} added {name} to #{number}")

    def unlabel(self, number, by, name="title-test"):
        self.github().as_(ANYPS5, by).remove_label(number, name)
        self.log(f"event: {by} removed {name} from #{number}")

    def command(self, number, body, by):
        comment_id = self.github().as_(ANYPS5, by).create_comment(number, body)
        self.log(f"event: {by} commented on #{number}: {body}")
        return comment_id

    def push(self, number, head, by):
        """A new head of the PR (the commit must be in the clone the stand-in borrows from), with its workflow run."""
        fake = self.github()
        anyps5 = fake.repo(ANYPS5)
        pull = anyps5["pulls"][str(number)]
        pull["head"] = head
        pull["commits"].append(head)
        anyps5["runs"].append({"head_sha": head, "created_at": formats.iso(formats.now()), "actor": by, "event": "pull_request", "branch": pull["head_ref"]})
        fake.save()
        git(self.anyps5_git, "update-ref", f"refs/pull/{number}/head", head)
        self.log(f"event: {by} pushed {head[:9]} to #{number}")

    # -- people on the results repository ------------------------------------------------------------------------------

    def registrations(self):
        fake = self.github()
        return [i for i in fake.as_(self.results_name, identity="reader").issues(state="open") if formats.payload(i["body"])[0] == "register"]

    def approve(self, issue, by):
        self.github().as_(self.results_name, by).add_labels(issue, ["approved"])
        self.log(f"event: {by} added approved to registration #{issue}")

    def decline(self, issue, by):
        self.github().as_(self.results_name, by).add_labels(issue, ["declined"])
        self.log(f"event: {by} added declined to registration #{issue}")

    def codes(self):
        return {d["user_code"]: device for device, d in self.github().data.get("device", {}).items() if not d["login"]}

    def authorize(self, user_code, login):
        fake = self.github()
        for device in fake.data.get("device", {}).values():
            if device["user_code"] == user_code:
                device["login"] = login
                fake.save()
                self.log(f"event: {login} entered the device code {user_code}")
                return True
        raise SystemExit(f"no device code {user_code}")
