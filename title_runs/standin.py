"""A local stand-in for GitHub and the results repository, until Charlie creates the real App and repository.

    root/results.git   a bare results repository: branches main (claims, results, the workflows) and state (config,
                       queue, comments), as on GitHub
    root/forge.json    the fake AnyPS5: its pull requests, accounts and the App's comments (relay/forge.py FakeForge)
    root/outbox/       every call the App would make, with the comment bodies
    root/anyps5.git    a stand-in AnyPS5 remote for the clients: main and the PRs' commits (objects borrowed from a local
                       clone through alternates)
    root/workflows.log what the stand-in workflows did

The workflows run as on GitHub, from this tool's code: the queue workflow on an event (label(), command(), push()) or a
refresh; the publish workflow from results.git's post-receive hook on every push to main that is not its own. The
pusher (GitHub's github.actor) is the pushed commit's author name here: the client commits as its tester.
"""

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from . import ROOT, export, formats
from .relay import forge as forges, publish, queue

BOT = "TITLE_RUNS_STANDIN_BOT"
HOOK = """#!/bin/sh
# The stand-in's publish workflow: on a push to main that the workflows did not make themselves.
[ -n "$TITLE_RUNS_STANDIN_BOT" ] && exit 0
while read old new ref; do
    [ "$ref" = refs/heads/main ] || continue
    actor="$(git log -1 --format=%an "$new")"
    env -u GIT_DIR -u GIT_QUARANTINE_PATH -u GIT_OBJECT_DIRECTORY -u GIT_ALTERNATE_OBJECT_DIRECTORIES -u GIT_PUSH_OPTION_COUNT \\
        python3 -I "{tool}" standin hook --root "{root}" --before "$old" --after "$new" --actor "$actor" >> "{root}/workflows.log" 2>&1
done
exit 0
"""


def clean_env(extra=None):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(extra or {})
    return env


def git(directory, *args, env=None, check=True):
    result = subprocess.run(["git", "-C", str(directory), *args], capture_output=True, text=True, env=clean_env(env))
    if check and result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args[:3])} in {directory}: {result.stderr.strip()[:300]}")
    return result.stdout.strip()


BOT_IDENTITY = {"GIT_AUTHOR_NAME": "title-runs[bot]", "GIT_AUTHOR_EMAIL": "bot@localhost", "GIT_COMMITTER_NAME": "title-runs[bot]",
                "GIT_COMMITTER_EMAIL": "bot@localhost"}


def create(root, repository, maintainers, testers, clone, main, pulls, associations, label="title-test"):
    """pulls: [{"number", "title", "author", "head"}]; clone: a local AnyPS5 clone holding main and the heads."""
    root = Path(root)
    if (root / "results.git").exists():
        raise SystemExit(f"{root} already holds a stand-in")
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as work:
        data, state = Path(work) / "main", Path(work) / "state"
        export.export(data, state, repository)
        config = json.loads((state / "config.json").read_text())
        config.update(maintainers=maintainers, testers=testers, label=label)
        (state / "config.json").write_text(json.dumps(config, indent=2) + "\n")
        git(root, "init", "-q", "--bare", "-b", "main", "results.git")
        for directory, branch in ((data, "main"), (state, "state")):
            git(work, "init", "-q", "-b", branch, str(directory))
            git(directory, "add", "-A")
            git(directory, "commit", "-qm", f"results repository: {branch}", env=BOT_IDENTITY)
            git(directory, "push", "-q", str(root / "results.git"), f"HEAD:{branch}", env={BOT: "1"})
    (root / "forge.json").write_text(json.dumps({
        "repository": repository, "associations": associations,
        "pulls": {str(p["number"]): {**p, "state": "open", "commits": [p["head"]]} for p in pulls}}, indent=2))
    git(root, "init", "-q", "--bare", "-b", "main", "anyps5.git")
    objects = Path(git(clone, "rev-parse", "--path-format=absolute", "--git-common-dir")) / "objects"
    (root / "anyps5.git" / "objects" / "info" / "alternates").write_text(f"{objects}\n")
    git(root / "anyps5.git", "update-ref", "refs/heads/main", main)
    for pull in pulls:
        git(root / "anyps5.git", "update-ref", f"refs/pull/{pull['number']}/head", pull["head"])
    hook = root / "results.git" / "hooks" / "post-receive"
    hook.write_text(HOOK.replace("{tool}", str(ROOT / "title-runs")).replace("{root}", str(root)))
    hook.chmod(0o755)
    return Standin(root)


class Standin:
    def __init__(self, root):
        self.root = Path(root)
        self.results = self.root / "results.git"
        self.anyps5 = self.root / "anyps5.git"

    def forge(self):
        return forges.FakeForge(self.root / "forge.json", self.root / "outbox")

    def log(self, text):
        with open(self.root / "workflows.log", "a") as stream:
            stream.write(f"{formats.iso(formats.now())} {text}\n")

    def checkouts(self, data_ref="main"):
        work = Path(tempfile.mkdtemp(dir=self.root, prefix="run-"))
        git(work, "clone", "-q", "--branch", "state", str(self.results), "state")
        git(work, "clone", "-q", str(self.results), "data")
        git(work / "data", "checkout", "-q", data_ref)
        return work, work / "state", work / "data"

    def commit_state(self, work, state, message):
        git(state, "add", "-A")
        if git(state, "status", "--porcelain"):
            git(state, "commit", "-qm", message, env=BOT_IDENTITY)
            git(state, "push", "-q", "origin", "HEAD:state", env={BOT: "1"})
        shutil.rmtree(work)

    def run_queue(self, name, payload=None, refresh=False):
        work, state, data = self.checkouts()
        workflow = queue.QueueWorkflow(state, data, self.forge(), self.anyps5, None, "main", log=lambda text: self.log(f"queue: {text}"))
        if refresh:
            workflow.refresh()
        else:
            workflow.handle(name, payload)
        changed = workflow.finish()
        self.commit_state(work, state, f"queue: {name}")
        return changed

    def run_publish(self, actor, before, after):
        work, state, data = self.checkouts(after)
        report = publish.publish(state, data, self.forge(), actor, before, after, log=lambda text: self.log(f"publish: {text}"))
        self.commit_state(work, state, f"publish: {after[:12]}")
        return report

    # -- events on the stand-in AnyPS5 ---------------------------------------------------------------------------------

    def pull(self, number):
        return json.loads((self.root / "forge.json").read_text())["pulls"][str(number)]

    def label(self, number, sender):
        pull = self.pull(number)
        payload = {"action": "labeled", "label": {"name": "title-test"}, "number": number, "sender": {"login": sender},
                   "pull_request": {"number": number, "title": pull["title"], "state": "open", "user": {"login": pull["author"]},
                                    "head": {"sha": pull["head"]}}}
        self.log(f"event: #{number} labelled title-test by {sender} at {pull['head'][:9]}")
        return self.run_queue("pull_request", payload)

    def command(self, number, body, sender, association):
        data = json.loads((self.root / "forge.json").read_text())
        comment_id = data.setdefault("next_comment", 900001)
        data["next_comment"] = comment_id + 1
        data.setdefault("comments", {})[str(comment_id)] = {"pr": number, "body": body, "user": sender}
        (self.root / "forge.json").write_text(json.dumps(data, indent=2))
        payload = {"action": "created", "issue": {"number": number, "pull_request": {}}, "sender": {"login": sender},
                   "comment": {"id": comment_id, "body": body, "user": {"login": sender}, "author_association": association}}
        self.log(f"event: #{number} comment by {sender} ({association}): {body}")
        return self.run_queue("issue_comment", payload)

    def push(self, number, head, sender):
        """A new head of the PR on the stand-in AnyPS5 (the commit must be in the clone the stand-in borrows from)."""
        data = json.loads((self.root / "forge.json").read_text())
        pull = data["pulls"][str(number)]
        before = pull["head"]
        pull["head"] = head
        pull["commits"].append(head)
        (self.root / "forge.json").write_text(json.dumps(data, indent=2))
        git(self.anyps5, "update-ref", f"refs/pull/{number}/head", head)
        payload = {"action": "synchronize", "number": number, "before": before, "after": head, "sender": {"login": sender},
                   "pull_request": {"number": number, "state": "open", "user": {"login": pull["author"]}, "head": {"sha": head}}}
        self.log(f"event: #{number} pushed {head[:9]} by {sender}")
        return self.run_queue("pull_request", payload)
