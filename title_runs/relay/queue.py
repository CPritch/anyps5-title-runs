"""The queue workflow: AnyPS5's events -> queue.json, the App's reactions and its comment on each queued PR.

Events arrive in the shape of GitHub's webhook payloads ("pull_request" labeled, unlabeled, synchronize, closed;
"issue_comment" created), forwarded from the App's webhook as repository_dispatch; a scheduled run refreshes every
queued PR's head instead (refresh()).

Approval is per commit (DESIGN.md, "Approval is per commit, not per PR"):
- a label pins the PR's head SHA from the label event's own payload; a command pins its sha= (any commit of the PR),
  else the PR's head when the workflow reads it;
- a push after approval leaves the entry on the approved head and is listed as not checked, unless the new head's own
  commits have the approved head's patch-ids, or the pusher is OWNER, MEMBER or COLLABORATOR and not the PR's author;
  then the approval is carried over to the new head.
"""

import json
import re
from pathlib import Path

from . import comment, patchids
from .. import formats
from .forge import TRUSTED_ASSOCIATIONS

COMMAND = re.compile(r"^/title-test(?:[ \t]+(.*))?$", re.M)
HEX = re.compile(r"[0-9a-f]{7,40}")


class CommandError(ValueError):
    pass


def parse_command(text):
    """The first /title-test line of a comment: {"stop": True} or {"priority", "titles", "hw", "machines", "sha"} with
    None for what the command does not set. Raises CommandError for anything not understood."""
    found = COMMAND.search(text.replace("\r\n", "\n"))
    if not found:
        return None
    out = {"stop": False, "priority": None, "titles": None, "hw": None, "machines": None, "sha": None}
    for token in (found.group(1) or "").split():
        key, eq, value = token.partition("=")
        if not eq:
            if token == "stop":
                out["stop"] = True
            elif token in formats.PRIORITIES:
                out["priority"] = token
            else:
                raise CommandError(f"{token!r} is not a priority or stop")
        elif key == "titles":
            out["titles"] = [t for t in value.split(",") if t]
            if not out["titles"] or not all(formats.TITLE_ID.fullmatch(t) for t in out["titles"]):
                raise CommandError(f"titles={value} is not a list of title IDs")
        elif key == "hw":
            out["hw"] = [t.replace("_", " ").lower() for t in value.split(",") if t]
            if not out["hw"]:
                raise CommandError("hw= is empty")
        elif key == "machines":
            if not value.isdigit() or not 1 <= int(value) <= 20:
                raise CommandError(f"machines={value} is not between 1 and 20")
            out["machines"] = int(value)
        elif key == "sha":
            if not HEX.fullmatch(value.lower()):
                raise CommandError(f"sha={value} is not 7 to 40 hex digits")
            out["sha"] = value.lower()
        else:
            raise CommandError(f"{key}= is not a /title-test option")
    if out["stop"] and any(out[k] is not None for k in ("priority", "titles", "hw", "machines", "sha")):
        raise CommandError("stop takes no options")
    return out


def load(path, default):
    return json.loads(path.read_text()) if path.exists() else default


class QueueWorkflow:
    """state: a checkout of the results repository's state branch (config.json, queue.json, comments.json), which only
    the workflows and the maintainers write; data: a checkout of its main branch (claims/, results/), which testers
    write. Results are read from data only for the comment."""

    def __init__(self, state, data, forge, git_dir=None, git_remote=None, main_ref="main", now=None, log=print):
        self.state, self.data, self.forge = Path(state), Path(data), forge
        self.git_dir, self.git_remote, self.main_ref = git_dir, git_remote, main_ref
        self.at = now or formats.now()
        self.log = log
        self.config = formats.check_config(json.loads((self.state / "config.json").read_text()))
        self.queue = formats.check_queue(load(self.state / "queue.json", formats.empty_queue(self.config["repository"])))
        self.comments = load(self.state / "comments.json", formats.empty_comments())
        self.changed = set()

    # -- helpers -------------------------------------------------------------------------------------------------------

    def maintainer(self, login, association=None):
        if login not in self.config["maintainers"]:
            return False
        return association is None or association in TRUSTED_ASSOCIATIONS

    def entry(self, pr):
        return next((e for e in self.queue["entries"] if e["pr"] == pr), None)

    def approve(self, pr, head, by, via, pinned, options):
        """Queue pr at the approved commit head (or move its entry there), with the command's options."""
        pull = self.forge.pull(pr)
        entry = self.entry(pr)
        stamp = formats.iso(self.at)
        if entry is None:
            entry = {"job": formats.job_id(pr, head), "pr": pr, "title": pull["title"][:200], "author": pull["author"], "head": head,
                     "approval": {"by": by, "at": stamp, "via": via, "pinned": pinned}, "priority": "normal", "titles": [], "hw": [],
                     "machines": formats.DEFAULT_MACHINES, "queued_by": by, "queued_at": stamp, "earlier": [], "unapproved": []}
            self.queue["entries"].append(entry)
            self.log(f"#{pr}: queued {head[:9]} ({via} by {by})")
        elif entry["head"] != head:
            entry["earlier"].append(entry["head"])
            entry.update(head=head, job=formats.job_id(pr, head), approval={"by": by, "at": stamp, "via": via, "pinned": pinned})
            self.log(f"#{pr}: approved {head[:9]} ({via} by {by}); earlier {entry['earlier'][-1][:9]}")
        entry["unapproved"] = [p for p in entry["unapproved"] if p["sha"] != head]
        for key in ("priority", "titles", "hw", "machines"):
            if options.get(key) is not None:
                entry[key] = options[key]
        self.queue["stopped"] = [s for s in self.queue.get("stopped", []) if s["pr"] != pr]
        self.changed.add(pr)
        return entry

    def stop(self, pr, by):
        entry = self.entry(pr)
        if entry is not None:
            self.queue["entries"].remove(entry)
        self.queue.setdefault("stopped", []).append({"pr": pr, "by": by, "at": formats.iso(self.at)})
        self.changed.add(pr)
        self.log(f"#{pr}: stopped by {by}")

    def carry(self, entry, new, reason):
        old = entry["head"]
        entry["earlier"].append(old)
        entry.update(head=new, job=formats.job_id(entry["pr"], new),
                     approval={"by": entry["approval"]["by"], "at": formats.iso(self.at), "via": "carried", "from": old, "reason": reason[:200]})
        entry["unapproved"] = []
        self.log(f"#{entry['pr']}: approval carried from {old[:9]} to {new[:9]}: {reason}")

    def pushed(self, pr, new, sender):
        """A new head of a queued PR: carried over, or listed as not checked."""
        entry = self.entry(pr)
        if entry is None or new == entry["head"] or any(p["sha"] == new for p in entry["unapproved"]):
            return
        self.changed.add(pr)
        association = self.forge.association(sender) if sender != "unknown" else "NONE"
        if sender != entry["author"] and association in TRUSTED_ASSOCIATIONS:
            return self.carry(entry, new, f"pushed by @{sender} ({association})")
        if self.git_dir is not None:
            patchids.ensure(self.git_dir, [entry["head"], new], self.git_remote)
            same, reason = patchids.same_code(self.git_dir, entry["head"], new, self.main_ref)
            if same:
                return self.carry(entry, new, reason)
        entry["unapproved"].append({"sha": new, "by": sender, "at": formats.iso(self.at)})
        self.log(f"#{pr}: {new[:9]} pushed after approval by {sender}: not checked")

    # -- events --------------------------------------------------------------------------------------------------------

    def handle(self, name, payload):
        action = payload.get("action")
        sender = payload.get("sender", {}).get("login", "unknown")
        if name == "pull_request":
            pr = payload["pull_request"]["number"]
            if action == "labeled" and payload.get("label", {}).get("name") == self.config["label"]:
                if not self.maintainer(sender):
                    return self.log(f"#{pr}: label by {sender}, not a maintainer: ignored")
                self.approve(pr, payload["pull_request"]["head"]["sha"], sender, "label", False, {})
            elif action == "unlabeled" and payload.get("label", {}).get("name") == self.config["label"] and self.maintainer(sender):
                self.stop(pr, sender)
            elif action == "synchronize":
                self.pushed(pr, payload["after"], sender)
            elif action == "closed" and self.entry(pr) is not None:
                self.queue["entries"].remove(self.entry(pr))
                self.changed.add(pr)
                self.log(f"#{pr}: closed; off the queue")
        elif name == "issue_comment" and action == "created" and "pull_request" in payload.get("issue", {}):
            self.command(payload["issue"]["number"], payload["comment"])

    def command(self, pr, note):
        login, association = note["user"]["login"], note.get("author_association", "NONE")
        try:
            options = parse_command(note.get("body", ""))
        except CommandError as error:
            self.log(f"#{pr}: command by {login} not understood: {error}")
            return self.forge.react(note["id"], "confused")
        if options is None:
            return
        if not self.maintainer(login, association):
            self.log(f"#{pr}: command by {login} ({association}), not a maintainer: refused")
            return self.forge.react(note["id"], "confused")
        if options["stop"]:
            self.stop(pr, login)
        else:
            if options["sha"]:
                matches = [sha for sha in self.forge.commits(pr) if sha.startswith(options["sha"])]
                if len(matches) != 1:
                    self.log(f"#{pr}: sha={options['sha']} names {len(matches)} commits of the PR")
                    return self.forge.react(note["id"], "confused")
                head, pinned = matches[0], True
            else:
                head, pinned = self.forge.pull(pr)["head"], False
            self.approve(pr, head, login, "command", pinned, options)
        self.forge.react(note["id"], "+1")

    def refresh(self):
        """Each queued PR's state and head as GitHub has them now (the scheduled run)."""
        for entry in list(self.queue["entries"]):
            pull = self.forge.pull(entry["pr"])
            if pull["state"] != "open":
                self.queue["entries"].remove(entry)
                self.changed.add(entry["pr"])
                self.log(f"#{entry['pr']}: {pull['state']}; off the queue")
            elif pull["head"] != entry["head"]:
                self.pushed(entry["pr"], pull["head"], "unknown")

    # -- output --------------------------------------------------------------------------------------------------------

    def finish(self):
        for pr in sorted(self.changed):
            comment.refresh(self.data, self.forge, self.queue, self.comments, pr, self.at)
        if self.changed:
            self.queue["updated"] = formats.iso(self.at)
        formats.check_queue(self.queue)
        (self.state / "queue.json").write_text(json.dumps(self.queue, indent=2) + "\n")
        (self.state / "comments.json").write_text(json.dumps(self.comments, indent=2) + "\n")
        return sorted(self.changed)
