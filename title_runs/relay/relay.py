"""The results repository's one workflow, relay (DESIGN.md, "Pieces"), one run: every 5 minutes on a schedule, as the App
on AnyPS5 and as the workflow on the results repository.

1. AnyPS5's events since the last run: `title-test` added by a maintainer queues the PR's head, if that head was
   pushed before the label (its PR workflow runs tell when, and who pushed); removed by a maintainer, it stops.
   `/title-test` commands from maintainers set options or pin a commit (sha=).
2. Each queued PR's head: a new head carries the approval over (the same patch-ids, or pushed by a collaborator who is
   not the author) or expires it: the App removes the label and says which commit expired it.
3. Registrations: a tester's issue with a `register` payload is pending until a maintainer adds `approved`
   (`declined` turns it down); the workflow then records the machine in registry.json and closes the issue.
4. Job issues: one per queued job, opened here, closed when the job leaves the queue.
5. Testers' comments on job issues: claims, withdrawals and results, accepted only from a registered machine's tester,
   a result only with that tester's live claim for the same head. Accepted results go to results/.
6. The App's comment on each PR that changed, and the overview issue.

Nothing depends on a run happening on time: cursors carry over and a late run catches up. State is written to the
checkout (the caller commits it); a failing step still saves what the steps before it did.
"""

import json
import subprocess
from pathlib import Path

from . import comment, overview, patchids
from .commands import CommandError, parse_command
from .. import formats, gh

APPROVED, DECLINED, REGISTRATION, JOB, OVERVIEW, TESTER_TRUST = "approved", "declined", "registration", "job", "overview", "tester-trust"
TRUSTED = ("OWNER", "MEMBER", "COLLABORATOR")
FILES = ("queue", "registry", "claims", "jobs", "comments", "cursors")


def load(path, default):
    return json.loads(path.read_text()) if path.exists() else default


class Relay:
    def __init__(self, state, anyps5, results, git_dir=None, git_remote=None, main_ref="origin/main", now=None, log=print):
        self.state, self.anyps5, self.results = Path(state), anyps5, results
        self.git_dir, self.git_remote, self.main_ref = git_dir, git_remote, main_ref
        self.at, self.log = now or formats.now(), log
        self.config = formats.check_config(json.loads((self.state / "config.json").read_text()))
        self.label = self.config.get("label", "title-test")
        self.queue = formats.check_queue(load(self.state / "queue.json", formats.empty_queue(self.config["repository"])))
        self.queue.setdefault("expired", [])
        self.queue.setdefault("refused", [])
        self.registry = load(self.state / "registry.json", formats.empty_registry())
        self.claims = load(self.state / "claims.json", {})
        self.jobs = load(self.state / "jobs.json", {})
        self.comments = load(self.state / "comments.json", formats.empty_comments())
        self.cursors = load(self.state / "cursors.json", {})
        self.changed = set()

    # -- helpers -------------------------------------------------------------------------------------------------------

    def stamp(self):
        return formats.iso(self.at)

    def maintainer(self, login, association=None):
        return login in self.config["maintainers"] and (association is None or association in TRUSTED)

    def is_bot(self, login):
        return not login or login.endswith("[bot]") or login == self.config.get("app", {}).get("bot")

    def entry(self, pr):
        return next((e for e in self.queue["entries"] if e["pr"] == pr), None)

    def push_time(self, sha):
        """When a head was pushed, and by whom: the first workflow run its push started on the PR."""
        runs = [r for r in self.anyps5.workflow_runs(head_sha=sha) if r["event"] in ("pull_request", "pull_request_target")]
        return (runs[0]["created_at"], runs[0]["actor"]) if runs else (None, None)

    def commit_time(self, sha):
        if self.git_dir is None:
            return None
        patchids.ensure(self.git_dir, [sha], self.git_remote)
        out = subprocess.run(["git", "--git-dir", str(self.git_dir), "log", "-1", "--format=%cI", sha], capture_output=True, text=True)
        return out.stdout.strip() or None

    def pin(self, pr, at, by, labelled):
        """The PR's head, if it was pushed before at (a label's or a command's time); otherwise None, recorded as refused
        (and the label taken off again)."""
        head = self.anyps5.pull(pr)["head"]
        pushed, _ = self.push_time(head)
        source = "its PR workflow run"
        if pushed is None:
            pushed, source = self.commit_time(head), "its commit date (no PR workflow run)"
        if pushed and formats.parse_time(pushed) > formats.parse_time(at):
            self.queue["refused"].append({"pr": pr, "by": by, "labelled": at, "head": head, "pushed": pushed, "source": source})
            if labelled:
                self.anyps5.remove_label(pr, self.label)
            self.changed.add(pr)
            self.log(f"#{pr}: not queued: {head[:9]} was pushed at {pushed}, after {by}'s {'label' if labelled else 'command'} at {at}")
            return None
        return head

    def close_job(self, job, reason):
        record = self.jobs.get(job)
        if record and record["state"] == "open":
            self.results.create_comment(record["issue"], reason)
            self.results.edit_issue(record["issue"], state="closed")
            record.update(state="closed", reason=reason[:200])

    # -- queue changes -------------------------------------------------------------------------------------------------

    def approve(self, pr, head, by, via, pinned, options):
        pull = self.anyps5.pull(pr)
        entry, stamp = self.entry(pr), self.stamp()
        if entry is None:
            entry = {"job": formats.job_id(pr, head), "pr": pr, "title": pull["title"][:200], "author": pull["author"], "head": head,
                     "approval": {"by": by, "at": stamp, "via": via, "pinned": pinned}, "priority": "normal", "titles": [], "hw": [],
                     "machines": formats.DEFAULT_MACHINES, "queued_by": by, "queued_at": stamp, "earlier": [], "unapproved": []}
            self.queue["entries"].append(entry)
            self.log(f"#{pr}: queued {head[:9]} ({via} by {by})")
        elif entry["head"] != head:
            self.close_job(entry["job"], f"Superseded: @{by} approved `{head[:9]}`.")
            entry["earlier"].append(entry["head"])
            entry.update(head=head, job=formats.job_id(pr, head), approval={"by": by, "at": stamp, "via": via, "pinned": pinned})
            entry.pop("issue", None)
            self.log(f"#{pr}: approved {head[:9]} ({via} by {by})")
        for key in ("priority", "titles", "hw", "machines"):
            if options.get(key) is not None:
                entry[key] = options[key]
        self.queue["stopped"] = [s for s in self.queue.get("stopped", []) if s["pr"] != pr]
        self.changed.add(pr)
        return entry

    def stop(self, pr, by, why=None):
        entry = self.entry(pr)
        if entry is not None:
            self.queue["entries"].remove(entry)
            self.close_job(entry["job"], why or f"Stopped by @{by}.")
        self.queue.setdefault("stopped", []).append({"pr": pr, "by": by, "at": self.stamp()})
        self.changed.add(pr)
        self.log(f"#{pr}: stopped by {by}")

    def carry(self, entry, new, reason):
        old = entry["head"]
        self.close_job(entry["job"], f"Superseded: the approval was carried over to `{new[:9]}` ({reason}).")
        entry["earlier"].append(old)
        entry.update(head=new, job=formats.job_id(entry["pr"], new),
                     approval={"by": entry["approval"]["by"], "at": self.stamp(), "via": "carried", "from": old, "reason": reason[:200]})
        entry.pop("issue", None)
        self.changed.add(entry["pr"])
        self.log(f"#{entry['pr']}: approval carried from {old[:9]} to {new[:9]}: {reason}")

    def expire(self, entry, new, pusher, at):
        self.queue["entries"].remove(entry)
        self.queue["expired"].append({"pr": entry["pr"], "head": entry["head"], "job": entry["job"], "by": new, "pusher": pusher, "at": at or self.stamp(),
                                      "approved_by": entry["approval"]["by"]})
        self.anyps5.remove_label(entry["pr"], self.label)
        self.close_job(entry["job"], f"Approval expired: `{new[:9]}` was pushed after it{' by @' + pusher if pusher else ''}. Nobody starts this job any more.")
        self.changed.add(entry["pr"])
        self.log(f"#{entry['pr']}: approval of {entry['head'][:9]} expired by {new[:9]} ({pusher or 'unknown pusher'})")

    def pushed(self, entry, new):
        pushed_at, pusher = self.push_time(new)
        if pushed_at and formats.parse_time(pushed_at) < formats.parse_time(entry["approval"]["at"]):
            # Already there when the maintainer approved an earlier commit (sha=): not a push after approval.
            entry["unapproved"].append({"sha": new, "by": pusher or "unknown", "at": pushed_at})
            self.changed.add(entry["pr"])
            return
        if pusher and pusher != entry["author"] and self.anyps5.permission(pusher) in gh.WRITE:
            return self.carry(entry, new, f"pushed by @{pusher}, a collaborator")
        if self.git_dir is not None:
            patchids.ensure(self.git_dir, [entry["head"], new], self.git_remote)
            same, reason = patchids.same_code(self.git_dir, entry["head"], new, self.main_ref)
            if same:
                return self.carry(entry, new, reason)
        self.expire(entry, new, pusher, pushed_at)

    # -- 1, 2: AnyPS5 --------------------------------------------------------------------------------------------------

    def anyps5_events(self):
        for event in self.anyps5.issue_events(self.cursors.get("anyps5_events", 0)):
            self.cursors["anyps5_events"] = max(self.cursors.get("anyps5_events", 0), event["id"])
            if event["label"] != self.label or event["issue"] is None or self.is_bot(event["actor"]):
                continue
            pr, actor = event["issue"], event["actor"]
            if event["event"] == "labeled":
                if not self.maintainer(actor):
                    self.log(f"#{pr}: {self.label} added by {actor}, not a maintainer: ignored")
                    continue
                head = self.pin(pr, event["created_at"], actor, labelled=True)
                if head:
                    self.approve(pr, head, actor, "label", False, {})
            elif event["event"] == "unlabeled" and self.maintainer(actor) and self.entry(pr):
                self.stop(pr, actor)

    def anyps5_commands(self):
        since, seen = self.cursors.get("anyps5_comments"), set(self.cursors.get("anyps5_comment_ids", []))
        newest, at_newest = since, set()
        for note in self.anyps5.comments(since=since):
            if note["id"] in seen:
                continue
            if not newest or note["created_at"] > newest:
                newest, at_newest = note["created_at"], set()
            at_newest.add(note["id"])
            if self.is_bot(note["user"]):
                continue
            try:
                options = parse_command(note["body"])
            except CommandError as error:
                self.log(f"#{note['issue']}: command by {note['user']} not understood: {error}")
                self.anyps5.react(note["id"], "confused")
                continue
            if options is None:
                continue
            pr = note["issue"]
            if not self.maintainer(note["user"], note["association"]):
                self.log(f"#{pr}: command by {note['user']} ({note['association']}), not a maintainer: refused")
                self.anyps5.react(note["id"], "confused")
                continue
            if options["stop"]:
                self.stop(pr, note["user"])
            elif options["sha"]:
                matches = [sha for sha in self.anyps5.commits(pr) if sha.startswith(options["sha"])]
                if len(matches) != 1:
                    self.anyps5.react(note["id"], "confused")
                    continue
                self.approve(pr, matches[0], note["user"], "command", True, options)
            else:
                head = self.pin(pr, note["created_at"], note["user"], labelled=False)
                if head is None:
                    self.anyps5.react(note["id"], "confused")
                    continue
                self.approve(pr, head, note["user"], "command", False, options)
            self.anyps5.react(note["id"], "+1")
        self.cursors["anyps5_comments"] = newest
        self.cursors["anyps5_comment_ids"] = sorted(at_newest | (seen if newest == since else set()))

    def refresh(self):
        for entry in list(self.queue["entries"]):
            pull = self.anyps5.pull(entry["pr"])
            if pull["state"] != "open":
                self.queue["entries"].remove(entry)
                self.close_job(entry["job"], f"#{entry['pr']} was {pull['state']}.")
                self.changed.add(entry["pr"])
                self.log(f"#{entry['pr']}: {pull['state']}; off the queue")
            elif pull["head"] != entry["head"] and pull["head"] not in [p["sha"] for p in entry.get("unapproved", [])]:
                self.pushed(entry, pull["head"])

    # -- 3, 4, 5: the results repository -------------------------------------------------------------------------------

    def registrations(self):
        for issue in self.results.issues(state="open"):
            kind, data = formats.payload(issue["body"])
            if kind != "register":
                continue
            try:
                formats.check_registration(data)
            except formats.FormatError as error:
                self.reply_once(issue["number"], f"Not a registration the client can read: {error}")
                continue
            key = formats.machine_key(data["tester"], data["machine"])
            if data["tester"] != issue["user"]:
                self.reply_once(issue["number"], f"Not accepted: the registration names {data['tester']}, but @{issue['user']} opened it.")
                self.results.edit_issue(issue["number"], state="closed")
                continue
            record = {"issue": issue["number"], "tester": data["tester"], "machine": data["machine"], "class": data["class"],
                      "titles": data.get("titles", []), "opened": issue["created_at"]}
            if key in self.registry["machines"]:
                self.registry["machines"][key].update(record)
                self.reply_once(issue["number"], f"{key} is registered already; its details are updated.")
                self.results.edit_issue(issue["number"], state="closed")
            elif key not in self.registry["pending"]:
                self.registry["pending"][key] = record
                self.results.add_labels(issue["number"], [REGISTRATION])
                self.log(f"registration {key} pending (#{issue['number']})")
        labels = {issue["number"]: issue["labels"] for issue in self.results.issues(state="open")}
        for key, record in list(self.registry["pending"].items()):
            for label in (APPROVED, DECLINED):
                if label not in labels.get(record["issue"], []):
                    continue
                actor = self.results.label_actor(record["issue"], label)
                if not self.maintainer(actor):
                    self.reply_once(record["issue"], f"`{label}` counts only from a maintainer ({', '.join('@' + m for m in self.config['maintainers'])}).")
                    continue
                del self.registry["pending"][key]
                if label == APPROVED:
                    self.registry["machines"][key] = {**record, "approved_by": actor, "approved_at": self.stamp()}
                    self.results.create_comment(record["issue"], f"Approved by @{actor}: {key} takes jobs from now on.")
                else:
                    self.registry["declined"][key] = {**record, "declined_by": actor, "declined_at": self.stamp()}
                    self.results.create_comment(record["issue"], f"Declined by @{actor}.")
                self.results.edit_issue(record["issue"], state="closed")
                self.log(f"registration {key}: {label} by {actor}")
                break

    def reply_once(self, issue, text):
        replied = self.cursors.setdefault("replied", [])
        if issue not in replied:
            self.results.create_comment(issue, text)
            replied.append(issue)

    def sync_jobs(self):
        anyps5 = self.config["repository"]
        for entry in self.queue["entries"]:
            if entry.get("issue"):
                continue
            job = {k: entry[k] for k in ("job", "pr", "head", "priority", "titles", "hw", "machines")}
            body = (f"Title runs of {anyps5}#{entry['pr']} at `{entry['head']}`, approved by @{entry['approval']['by']}. Testers' clients "
                    f"claim and report here; comments from accounts without a registered machine are not used.\n\n```json\n"
                    f"{formats.json_dumps(job)}\n```\n")
            number = self.results.create_issue(f"Job {entry['job']}: {anyps5}#{entry['pr']} {entry['title'][:60]}", body, [JOB])
            entry["issue"] = number
            self.jobs[entry["job"]] = {"issue": number, "pr": entry["pr"], "head": entry["head"], "state": "open"}
            self.log(f"#{entry['pr']}: job issue #{number} for {entry['job']}")

    def trust_issue(self):
        number = self.cursors.get("tester_trust_issue")
        if number is None:
            number = self.results.create_issue("Runs on testers' own trust",
                                               "Results of heads no maintainer approved, run by testers after their client's trust dialog. "
                                               "They are posted on the PR apart from the maintainers' queue.", [TESTER_TRUST])
            self.cursors["tester_trust_issue"] = number
        return number

    def refuse(self, issue, user, reason):
        self.results.create_comment(issue, f"@{user}: not used: {reason}")
        self.log(f"#{issue}: {user}'s comment not used: {reason}")

    def job_comments(self):
        since, seen = self.cursors.get("results_comments"), set(self.cursors.get("results_comment_ids", []))
        newest, at_newest = since, set()
        by_issue = {record["issue"]: job for job, record in self.jobs.items()}
        trust_issue = self.trust_issue()
        for note in self.results.comments(since=since):
            if note["id"] in seen:
                continue
            if not newest or note["created_at"] > newest:
                newest, at_newest = note["created_at"], set()
            at_newest.add(note["id"])
            kind, data = formats.payload(note["body"])
            if kind not in ("claim", "withdraw", "result") or self.is_bot(note["user"]):
                continue
            if data is None or not isinstance(data, dict):
                self.refuse(note["issue"], note["user"], "no JSON block the workflow can read")
                continue
            key = formats.machine_key(note["user"], str(data.get("machine")))
            if key not in self.registry["machines"]:
                self.log(f"#{note['issue']}: {key} is not a registered machine: ignored")
                continue
            if note["issue"] == trust_issue and kind == "result":
                self.accept_trusted(note, data)
                continue
            job = by_issue.get(note["issue"])
            if job is None:
                continue
            try:
                if kind == "claim":
                    claim = formats.check_claim(data, formats.claim_path(job, data["machine"]))
                    if claim["tester"] != note["user"] or claim["head"] != self.jobs[job]["head"]:
                        raise formats.FormatError("the claim's tester or head is not this comment's or this job's")
                    self.claims.setdefault(job, {})[claim["machine"]] = {**claim, "comment": note["id"]}
                elif kind == "withdraw":
                    if self.claims.get(job, {}).get(data["machine"], {}).get("tester") == note["user"]:
                        del self.claims[job][data["machine"]]
                else:
                    self.accept(job, note, data)
            except (formats.FormatError, KeyError, TypeError) as error:
                self.refuse(note["issue"], note["user"], str(error))
        self.cursors["results_comments"] = newest
        self.cursors["results_comment_ids"] = sorted(at_newest | (seen if newest == since else set()))

    def accept(self, job, note, data):
        path = formats.result_path(job, str(data.get("machine")))
        result = formats.check_result(data, path)
        if result["tester"] != note["user"]:
            raise formats.FormatError(f"the result names {result['tester']}, the comment is @{note['user']}'s")
        if result["trust"] != "queue" or result["head"] != self.jobs[job]["head"]:
            raise formats.FormatError("a job issue takes results of its own approved head only")
        claim = self.claims.get(job, {}).get(result["machine"])
        if claim is None or claim["tester"] != note["user"]:
            raise formats.FormatError(f"no claim of {result['machine']} for this job")
        if not formats.parse_time(claim["claimed"]) <= formats.parse_time(note["created_at"]) <= formats.parse_time(claim["expires"]):
            raise formats.FormatError(f"the result came {note['created_at']}, outside its claim ({claim['claimed']} to {claim['expires']})")
        self.store(path, result, note)

    def accept_trusted(self, note, data):
        try:
            path = formats.result_path(str(data.get("job")), str(data.get("machine")))
            result = formats.check_result(data, path)
            if result["tester"] != note["user"] or result["trust"] != "tester":
                raise formats.FormatError("a tester-trust result must be the commenter's and marked tester")
            if result["head"] not in self.anyps5.commits(result["pr"]):
                raise formats.FormatError(f"{result['head'][:9]} is not a commit of #{result['pr']}")
        except (formats.FormatError, gh.GitHubError) as error:
            return self.refuse(note["issue"], note["user"], str(error))
        self.store(path, result, note)

    def store(self, path, result, note):
        target = self.state / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(formats.json_dumps({**result, "comment": note["id"], "accepted_at": self.stamp()}) + "\n")
        key = formats.machine_key(result["tester"], result["machine"])
        self.registry["machines"][key]["last_report"] = note["created_at"]
        self.changed.add(result["pr"])
        self.log(f"accepted {path} from @{note['user']}")

    # -- 6: what people see ----------------------------------------------------------------------------------------------

    def update_comments(self):
        for pr in sorted(self.changed):
            posted = comment.refresh(self.state, self.anyps5, self.queue, self.comments, pr, self.at, self.label)
            if posted:
                self.log(f"#{pr}: {posted[0]} comment ({posted[1]})")

    def update_overview(self):
        """Edit the overview issue when what it shows changed (compared without its time, so an unchanged overview costs
        no write: edits count against GitHub's content-creation limit)."""
        data = overview.view(self.state, self.queue, self.registry, self.claims, self.jobs, self.stamp())
        steady = comment.digest(overview.render({**data, "last_run": None}, self.config["repository"], self.label))
        number = self.cursors.get("overview_issue")
        if number is not None and steady == self.cursors.get("overview_sha256"):
            return
        body = overview.render(data, self.config["repository"], self.label)
        if number is None:
            self.cursors["overview_issue"] = self.results.create_issue("Overview", body, [OVERVIEW])
        else:
            self.results.edit_issue(number, body=body)
        self.cursors["overview_sha256"] = steady

    def run(self, refresh=True):
        try:
            self.anyps5_events()
            self.anyps5_commands()
            if refresh:
                self.refresh()
            self.registrations()
            self.sync_jobs()
            self.job_comments()
            self.update_comments()
            self.update_overview()
        finally:
            self.cursors["last_run"] = self.stamp()
            self.save()
        return sorted(self.changed)

    def save(self):
        self.queue["updated"] = self.stamp() if self.changed else self.queue.get("updated", self.stamp())
        formats.check_queue(self.queue)
        for name in FILES:
            (self.state / f"{name}.json").write_text(json.dumps(getattr(self, name), indent=1, sort_keys=True) + "\n")
