"""The relay workflow (title_runs/relay/relay.py) against the fake GitHub: labels and commands queue approved heads, a
push expires an approval and the App takes the label off, testers register and report through comments, the App's
comment and the overview."""

import json
import unittest

from relay_helpers import NVIDIA_TOO, Stand, claim, result

from title_runs import formats
from title_runs.relay.commands import CommandError, parse_command


def comment(stand, kind, data, user="CPritch", issue=None):
    body = formats.payload_body(kind, data, f"A {kind} from the client.")
    return stand.user(user).create_comment(issue, body)


def queued_stand():
    stand = Stand()
    issue = stand.register()
    stand.at("2026-10-21T11:30:00Z").approve_machine(issue)
    stand.at("2026-10-21T11:35:00Z").poll()
    stand.at("2026-10-21T11:50:00Z").label()
    stand.at("2026-10-21T11:55:00Z").poll()
    return stand


class Commands(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(parse_command("/title-test high titles=PPSA04263 hw=amd,windows machines=3")["machines"], 3)
        with self.assertRaises(CommandError):
            parse_command("/title-test urgent")


class Label(unittest.TestCase):
    def test_a_label_queues_the_head_pushed_before_it(self):
        stand = queued_stand()
        entry = stand.queued()["entries"][0]
        self.assertEqual((entry["head"], entry["approval"]["via"], entry["approval"]["by"]), (stand.history.A, "label", "CPritch"))
        job = stand.issue(entry["issue"])
        self.assertTrue(job["title"].startswith(f"Job {entry['job']}"))
        self.assertIn("job", job["labels"])
        self.assertIn(f"Queued `{stand.history.A[:9]}` for title runs", stand.bodies()[-1])
        self.assertEqual(stand.pull_labels(), ["title-test"])

    def test_a_head_pushed_after_the_label_is_not_queued(self):
        stand = Stand()
        stand.at("2026-10-21T11:50:00Z").label()
        stand.at("2026-10-21T11:52:00Z").push(stand.history.B)
        stand.at("2026-10-21T11:55:00Z").poll()
        q = stand.queued()
        self.assertEqual(q["entries"], [])
        self.assertEqual((q["refused"][0]["head"], q["refused"][0]["source"]), (stand.history.B, "its PR workflow run"))
        self.assertEqual(stand.pull_labels(), [])
        self.assertIn(f"did not queue anything: the head `{stand.history.B[:9]}` was pushed after it", stand.bodies()[-1])
        self.assertEqual(len(stand.calls(action="comment")), 1)  # the first comment on the PR is new anyway

    def test_a_head_without_a_run_needs_a_sha_command(self):
        stand = Stand()
        stand.at("2026-10-21T09:00:00Z").push(stand.history.R, run=False)  # no PR workflow run for R; its commit date is 10:00
        stand.at("2026-10-21T11:30:00Z").label()  # after the commit date, which no longer counts
        stand.at("2026-10-21T11:35:00Z").poll()
        q = stand.queued()
        self.assertEqual((q["entries"], q["refused"][0]["source"], q["refused"][0]["pushed"]), ([], "no PR workflow run", None))
        self.assertEqual(stand.pull_labels(), [])
        self.assertIn(f"has no PR workflow run, so nothing tells when it was pushed and a label cannot approve it. Comment "
                      f"`/title-test sha={stand.history.R[:9]}`", stand.bodies()[-1])
        stand.at("2026-10-21T11:40:00Z").command(f"/title-test sha={stand.history.R[:9]}")
        stand.at("2026-10-21T11:45:00Z").poll()
        entry = stand.queued()["entries"][0]
        self.assertEqual((entry["head"], entry["approval"]["via"], entry["approval"]["pinned"]), (stand.history.R, "command", True))

    def test_a_refused_label_and_a_second_refusal_each_post_a_new_comment(self):
        stand = queued_stand()
        h = stand.history
        stand.at("2026-10-21T12:20:00Z").push(h.B, actor="Celegans12", run=False)  # other code, and no run to time it
        stand.at("2026-10-21T12:25:00Z").poll()  # expired: a new comment
        self.assertEqual(stand.queued()["expired"][0]["by"], h.B)
        stand.at("2026-10-21T12:30:00Z").label()
        stand.at("2026-10-21T12:35:00Z").poll()  # refused: no run for B, another new comment
        self.assertEqual(stand.queued()["refused"][0]["source"], "no PR workflow run")
        self.assertEqual(len(stand.calls(who="title-runs[bot]", action="comment")), 3)

    def test_a_label_by_someone_else_is_ignored(self):
        stand = Stand()
        stand.label(actor="Celegans12")
        stand.poll()
        self.assertEqual(stand.queued()["entries"], [])

    def test_unlabel_by_a_maintainer_stops(self):
        stand = queued_stand()
        stand.at("2026-10-21T12:10:00Z").unlabel()
        stand.at("2026-10-21T12:15:00Z").poll()
        self.assertEqual(stand.queued()["entries"], [])
        issue = stand.issue(stand.relay.jobs[formats.job_id(8104, stand.history.A)]["issue"])
        self.assertEqual(issue["state"], "closed")

    def test_a_second_poll_changes_nothing(self):
        stand = queued_stand()
        before = len(stand.calls())
        stand.at("2026-10-21T12:00:00Z").poll()
        self.assertEqual(len(stand.calls()), before)


class Command(unittest.TestCase):
    def test_options_sha_and_reaction(self):
        stand = Stand()
        stand.push(stand.history.B)
        note = stand.at("2026-10-21T12:01:00Z").command(f"/title-test high hw=amd sha={stand.history.A[:7]}")
        stand.at("2026-10-21T12:05:00Z").poll()
        entry = stand.queued()["entries"][0]
        self.assertEqual((entry["head"], entry["priority"], entry["hw"], entry["approval"]["pinned"]), (stand.history.A, "high", ["amd"], True))
        self.assertEqual(stand.calls("title-runs[bot]", "react")[-1]["content"], "+1")
        self.assertEqual(stand.calls("title-runs[bot]", "react")[-1]["path"].rsplit("/", 2)[-2], str(note))

    def test_refused_commands(self):
        for actor, body in (("Celegans12", "/title-test high"), ("CPritch", "/title-test urgent")):
            stand = Stand()
            stand.command(body, actor)
            stand.poll()
            self.assertEqual(stand.queued()["entries"], [])
            self.assertEqual(stand.calls("title-runs[bot]", "react")[-1]["content"], "confused")


class Push(unittest.TestCase):
    def test_a_push_by_the_author_expires_the_approval_and_the_label(self):
        stand = queued_stand()
        h = stand.history
        stand.at("2026-10-21T12:20:00Z").push(h.B, actor="Celegans12")
        stand.at("2026-10-21T12:25:00Z").poll()
        q = stand.queued()
        self.assertEqual(q["entries"], [])
        self.assertEqual({k: q["expired"][0][k] for k in ("head", "by", "pusher")}, {"head": h.A, "by": h.B, "pusher": "Celegans12"})
        self.assertEqual(stand.pull_labels(), [])
        body = stand.bodies()[-1]
        self.assertIn(f"**Approval of `{h.A[:9]}` expired**: `{h.B[:9]}` was pushed after it by @Celegans12", body)
        self.assertIn("The App removed `title-test`", body)
        self.assertEqual(len(stand.calls(who="title-runs[bot]", action="comment")), 2)  # queued, then expired: a new comment
        self.assertEqual(stand.relay.comments["prs"]["8104"]["posts"][-1]["reason"], f"the approval of {h.A[:9]} expired")
        job = stand.issue(stand.relay.jobs[formats.job_id(8104, h.A)]["issue"])
        self.assertEqual(job["state"], "closed")
        stand.at("2026-10-21T12:30:00Z").poll()  # the App's own removal is not a maintainer stopping it
        self.assertEqual(stand.queued()["stopped"], [])

    def test_labelling_again_queues_the_new_head(self):
        stand = queued_stand()
        h = stand.history
        stand.at("2026-10-21T12:20:00Z").push(h.B)
        stand.at("2026-10-21T12:25:00Z").poll()
        stand.at("2026-10-21T12:40:00Z").label()
        stand.at("2026-10-21T12:45:00Z").poll()
        self.assertEqual(stand.queued()["entries"][0]["head"], h.B)
        body = stand.bodies()[-1]
        top, _, rest = body.partition("<summary>Earlier heads</summary>")
        self.assertNotIn("expired", top)  # once the new head is queued the notice leaves the top
        self.assertIn(f"- **Approval of `{h.A[:9]}` expired**: `{h.B[:9]}` was pushed after it", rest)
        self.assertIn("The App removed `title-test`.", rest)

    def test_a_rebase_with_the_same_patch_ids_is_carried_over(self):
        stand = queued_stand()
        stand.at("2026-10-21T12:20:00Z").push(stand.history.R)
        stand.at("2026-10-21T12:25:00Z").poll()
        entry = stand.queued()["entries"][0]
        self.assertEqual((entry["head"], entry["approval"]["via"]), (stand.history.R, "carried"))
        self.assertEqual(stand.pull_labels(), ["title-test"])

    def test_a_push_by_a_collaborator_is_carried_over(self):
        stand = queued_stand()
        stand.at("2026-10-21T12:20:00Z").push(stand.history.B, actor="collab")
        stand.at("2026-10-21T12:25:00Z").poll()
        self.assertEqual(stand.queued()["entries"][0]["approval"]["reason"], "pushed by @collab, a collaborator")


class Registration(unittest.TestCase):
    def test_pending_until_a_maintainer_adds_approved(self):
        stand = Stand()
        issue = stand.register()
        stand.poll()
        self.assertIn("CPritch/laptop", stand.registry()["pending"])
        self.assertIn("registration", stand.issue(issue)["labels"])
        stand.approve_machine(issue, actor="Celegans12")
        stand.poll()
        stand.poll()  # seen again on every run, counted once
        self.assertEqual(stand.registry()["machines"], {})
        self.assertEqual(stand.issue_comments(issue), [])  # no reply
        self.assertEqual(stand.relay.cursors["ignored"]["counts"], {"label": 1})
        stand.user("CPritch").remove_label(issue, "approved")
        stand.approve_machine(issue)
        stand.poll()
        machine = stand.registry()["machines"]["CPritch/laptop"]
        self.assertEqual((machine["approved_by"], stand.issue(issue)["state"]), ("CPritch", "closed"))
        self.assertIn("Approved by @CPritch", stand.issue_comments(issue)[-1]["body"])

    def test_declined(self):
        stand = Stand()
        issue = stand.register()
        stand.poll()
        stand.approve_machine(issue, label="declined")
        stand.poll()
        self.assertIn("CPritch/laptop", stand.registry()["declined"])

    def test_a_registration_for_someone_else_is_ignored(self):
        stand = Stand()
        issue = stand.register(tester="CPritch", opened_by="mallory")
        stand.poll()
        stand.poll()
        self.assertEqual(stand.registry()["pending"], {})
        self.assertEqual((stand.issue(issue)["state"], stand.issue_comments(issue)), ("open", []))  # no write at all
        self.assertEqual(stand.relay.cursors["ignored"]["counts"], {"registration": 1})


class Reports(unittest.TestCase):
    def setUp(self):
        self.stand = queued_stand()
        self.h = self.stand.history
        self.issue = self.stand.queued()["entries"][0]["issue"]

    def report(self, at="2026-10-21T12:50:00Z", user="CPritch", data=None, claimed="2026-10-21T12:00:00Z"):
        self.stand.at("2026-10-21T12:00:00Z")
        comment(self.stand, "claim", claim(self.h.A, claimed=claimed), user, self.issue)
        self.stand.at(at)
        comment(self.stand, "result", data or result(self.h.A), user, self.issue)
        self.stand.at(max(at, "2026-10-21T13:00:00Z")).poll()  # ISO times in UTC compare as strings

    def test_a_claimed_result_is_accepted_and_shown(self):
        self.report()
        path = self.stand.state / "results" / formats.job_id(8104, self.h.A) / "laptop.json"
        self.assertTrue(path.exists())
        body = self.stand.bodies()[-1]
        self.assertIn("| laptop | NVIDIA GeForce RTX 5060 Laptop GPU, NVIDIA 615.71.09, Linux 7.2.8 | Grand Theft Auto V (PPSA04263) | rendering / rendering | "
                      "78.0 → 77.7 ms | no difference (borderline) |", body)
        self.assertIn("PPSA04263: No difference on 1 of 1 RTX 5060 Laptop GPU · NVIDIA 615 · Linux machine, median -0.35 ms", body)
        self.assertIn("borderline, one more machine of this class wanted", body)
        self.assertEqual(self.stand.registry()["machines"]["CPritch/laptop"]["last_report"], "2026-10-21T12:50:00Z")

    def test_the_comment_uses_config_jsons_threshold(self):
        config = json.loads((self.stand.state / "config.json").read_text())
        config["verdicts"] = {"threshold_pct": 0.3, "class_max": 3}
        (self.stand.state / "config.json").write_text(json.dumps(config))
        self.report()
        body = self.stand.bodies()[-1]
        self.assertIn("| 78.0 → 77.7 ms | **faster** |", body)
        self.assertIn("0.3 % of main 0.23 ms", body)
        self.assertIn("**Faster** on 1 of 1 RTX 5060 Laptop GPU · NVIDIA 615 · Linux machine", body)

    def test_a_second_machine_of_the_class_settles_the_combined_verdict(self):
        self.report()
        second = self.stand.register(machine="laptop-2", info=NVIDIA_TOO)
        self.stand.at("2026-10-21T13:10:00Z").approve_machine(second)
        self.stand.at("2026-10-21T13:15:00Z").poll()
        comment(self.stand, "claim", claim(self.h.A, "laptop-2", claimed="2026-10-21T13:15:00Z", info=NVIDIA_TOO), "CPritch", self.issue)
        self.stand.at("2026-10-21T14:00:00Z")
        comment(self.stand, "result", result(self.h.A, "laptop-2", a=(78.1, 77.8), b=(78.2, 77.9), info=NVIDIA_TOO), "CPritch", self.issue)
        self.stand.at("2026-10-21T14:05:00Z").poll()
        body = self.stand.bodies()[-1]
        self.assertIn("PPSA04263: No difference on 2 of 2 RTX 5060 Laptop GPU · NVIDIA 615 · Linux machines, median -0.12 ms", body)
        self.assertNotIn("borderline, one more", body)

    def test_unregistered_results_are_ignored(self):
        self.report(user="mallory", data=result(self.h.A, tester="mallory"))
        self.assertFalse((self.stand.state / "results").exists())

    def test_a_result_after_its_claim_expired_is_ignored(self):
        self.report(at="2026-10-21T15:00:01Z")
        self.assertFalse((self.stand.state / "results").exists())
        self.assertEqual(self.stand.relay.cursors["ignored"]["counts"], {"result": 1})
        self.assertIn("outside its claim", self.stand.relay.cursors["ignored"]["recent"][-1]["detail"])

    def test_a_result_without_a_claim_is_ignored_without_a_reply(self):
        comment(self.stand, "result", result(self.h.A), "CPritch", self.issue)
        self.stand.at("2026-10-21T13:00:00Z").poll()
        self.assertTrue(all(formats.payload(c["body"])[0] for c in self.stand.issue_comments(self.issue)))  # only the tester's own
        self.assertIn("no claim of laptop", self.stand.relay.cursors["ignored"]["recent"][-1]["detail"])

    def test_spam_is_counted_in_the_overview_and_answered_by_nothing(self):
        before = len(self.stand.calls())
        for user in ("spammer1", "spammer2"):
            self.stand.user(user).create_comment(self.issue, "buy things")
        comment(self.stand, "result", result(self.h.A, tester="mallory", machine="box"), "mallory", self.issue)
        self.stand.at("2026-10-21T13:00:00Z").poll()
        writes = [c for c in self.stand.calls()[before:] if c["as"] != "spammer1" and c["as"] != "spammer2" and c["as"] != "mallory"]
        self.assertTrue(all(c["action"] == "edit-issue" for c in writes), writes)  # the overview's edit, nothing else
        body = self.stand.issue(self.stand.relay.cursors["overview_issue"])["body"]
        self.assertIn("### Ignored, without a reply", body)
        self.assertIn("2 without a title-runs payload; 1 from accounts without a registered machine", body)

    def test_a_result_for_another_head_is_refused(self):
        self.report(data=result(self.h.B))
        self.assertFalse((self.stand.state / "results").exists())

    def test_tester_trust_results_are_shown_apart(self):
        self.stand.push(self.h.B, actor="collab")
        self.stand.at("2026-10-21T12:30:00Z").poll()
        trust = self.stand.relay.cursors["tester_trust_issue"]
        comment(self.stand, "result", result(self.h.B, trust="tester"), "CPritch", trust)
        self.stand.at("2026-10-21T13:00:00Z").poll()
        self.assertIn(f"**Run on the tester's trust** (`{self.h.B[:9]}`", self.stand.bodies()[-1])

    def test_the_overview(self):
        self.report()
        body = self.stand.issue(self.stand.relay.cursors["overview_issue"])["body"]
        for text in ("### Queue", f"| CPritch/AnyPS5#8104 | `{self.h.A[:9]}` | @CPritch (label) |", "no difference on 1 of 1",
                     "one more RTX 5060 Laptop GPU · NVIDIA 615 · Linux (borderline)", "### Machines", "| CPritch/laptop | RTX 5060 Laptop GPU · NVIDIA 615 · Linux |",
                     "2026-10-21 12:50 UTC", "### Pending registrations"):
            self.assertIn(text, body)
        self.assertNotIn("running:", body)  # the laptop's claim ended with its result


class CommandLine(unittest.TestCase):
    def test_poll_step(self):
        import subprocess
        from title_runs import ROOT
        stand = Stand()
        stand.label()
        done = subprocess.run(["python3", "-I", str(ROOT / "title-runs"), "relay", "poll", "--state", str(stand.state), "--anyps5-git",
                               str(stand.history.git_dir), "--main-ref", "main", "--fake", f"{stand.root / 'github.json'}:{stand.root / 'outbox'}"],
                              capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(json.loads((stand.state / "queue.json").read_text())["entries"][0]["head"], stand.history.A)


if __name__ == "__main__":
    unittest.main()
