import unittest

from relay_helpers import Stand, claim, event, result

from title_runs import formats, schedule
from title_runs.relay import patchids, queue


def label(stand, head, sender="CPritch"):
    return stand.queue_event("pull_request", event("labeled", HEAD=head, SENDER=sender))


def command(stand, body, sender="CPritch", association="OWNER", comment_id=501):
    return stand.queue_event("issue_comment", event("comment", BODY=body, SENDER=sender, ASSOCIATION=association, COMMENT_ID=comment_id))


def push(stand, before, after, sender="Celegans12"):
    stand.set_head(after)
    return stand.queue_event("pull_request", event("synchronize", BEFORE=before, HEAD=after, SENDER=sender))


class Commands(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(queue.parse_command("thanks\n/title-test high titles=PPSA04263,PPSA01325 hw=amd,intel,windows machines=3\n"),
                         {"stop": False, "priority": "high", "titles": ["PPSA04263", "PPSA01325"], "hw": ["amd", "intel", "windows"],
                          "machines": 3, "sha": None})
        self.assertEqual(queue.parse_command("/title-test")["priority"], None)
        self.assertTrue(queue.parse_command("/title-test stop")["stop"])
        self.assertEqual(queue.parse_command("/title-test sha=8D4F486")["sha"], "8d4f486")
        self.assertIsNone(queue.parse_command("no command here; /title-test is mentioned mid-line"))
        for bad in ("/title-test urgent", "/title-test machines=99", "/title-test titles=GTAV", "/title-test sha=xyz", "/title-test stop high",
                    "/title-test colour=red"):
            with self.assertRaises(queue.CommandError):
                queue.parse_command(bad)


class Label(unittest.TestCase):
    def test_label_pins_the_head_in_the_event(self):
        stand = Stand()
        h = stand.history
        stand.set_head(h.B)  # a push landed after the label, before the workflow ran
        label(stand, h.A)
        entry = stand.queued()["entries"][0]
        self.assertEqual(entry["head"], h.A)
        self.assertEqual(entry["job"], formats.job_id(8104, h.A))
        self.assertEqual(entry["approval"]["via"], "label")
        calls = stand.outbox_calls()
        self.assertEqual([c["action"] for c in calls], ["new"])
        self.assertIn(f"Queued `{h.A[:9]}` for title runs", stand.bodies()[0])

    def test_label_by_someone_else_is_ignored(self):
        stand = Stand()
        label(stand, stand.history.A, sender="Celegans12")
        self.assertEqual(stand.queued()["entries"], [])
        self.assertEqual(stand.outbox_calls(), [])

    def test_unlabel_stops(self):
        stand = Stand()
        label(stand, stand.history.A)
        stand.queue_event("pull_request", event("unlabeled", HEAD=stand.history.A, SENDER="CPritch"))
        self.assertEqual(stand.queued()["entries"], [])
        self.assertEqual(stand.queued()["stopped"][0]["pr"], 8104)

    def test_closed_leaves_the_queue(self):
        stand = Stand()
        label(stand, stand.history.A)
        stand.queue_event("pull_request", event("closed", HEAD=stand.history.A, SENDER="CPritch"))
        self.assertEqual(stand.queued()["entries"], [])


class Command(unittest.TestCase):
    def test_options_and_reaction(self):
        stand = Stand()
        command(stand, "/title-test high titles=PPSA04263 hw=amd,windows machines=3")
        entry = stand.queued()["entries"][0]
        self.assertEqual((entry["priority"], entry["titles"], entry["hw"], entry["machines"]), ("high", ["PPSA04263"], ["amd", "windows"], 3))
        self.assertEqual(entry["approval"]["via"], "command")
        self.assertIn({"action": "react", "request": {"method": "POST", "path": "/repos/CPritch/AnyPS5/issues/comments/501/reactions",
                                                      "json": {"content": "+1"}}, "content": "+1"}, stand.outbox_calls())

    def test_sha_pins_an_earlier_commit(self):
        stand = Stand()
        h = stand.history
        stand.set_head(h.B)
        command(stand, f"/title-test sha={h.A[:7]}")
        entry = stand.queued()["entries"][0]
        self.assertEqual(entry["head"], h.A)
        self.assertTrue(entry["approval"]["pinned"])

    def test_sha_not_in_the_pr(self):
        stand = Stand()
        command(stand, "/title-test sha=abcdef1")
        self.assertEqual(stand.queued()["entries"], [])
        self.assertEqual(stand.outbox_calls()[-1]["content"], "confused")

    def test_refused_commands(self):
        for sender, association, body in (("Celegans12", "CONTRIBUTOR", "/title-test high"),  # not a maintainer
                                          ("notreally", "NONE", "/title-test high"),  # listed, but no association with the repository
                                          ("CPritch", "OWNER", "/title-test urgent")):  # not understood
            stand = Stand()
            command(stand, body, sender, association)
            self.assertEqual(stand.queued()["entries"], [], body)
            self.assertEqual([c.get("content") for c in stand.outbox_calls()], ["confused"])

    def test_stop(self):
        stand = Stand()
        command(stand, "/title-test")
        command(stand, "/title-test stop", comment_id=502)
        self.assertEqual(stand.queued()["entries"], [])
        self.assertIn("Off the queue (stopped by @CPritch)", stand.bodies()[-1])


class PushAfterApproval(unittest.TestCase):
    def test_a_push_after_the_label_must_not_run(self):
        stand = Stand()
        h = stand.history
        label(stand, h.A)
        push(stand, h.A, h.B, sender="Celegans12")
        q = stand.queued()
        entry = q["entries"][0]
        self.assertEqual(entry["head"], h.A)
        self.assertEqual([p["sha"] for p in entry["unapproved"]], [h.B])
        self.assertIn(f"`{h.B[:9]}` pushed after approval by @Celegans12: **not checked**", stand.bodies()[-1])
        machine = schedule.Machine("laptop", "CPritch", formats.machine_class("NVIDIA GeForce RTX 5060 Laptop GPU", "Linux"), {"PPSA04263"})
        chosen = schedule.choose(q, machine, {}, {})
        self.assertEqual(chosen.entry["head"], h.A)
        self.assertNotIn(formats.job_id(8104, h.B), [c.job for c in schedule.rank(q, machine, {}, {})])

    def test_refresh_without_an_event_is_not_approved_either(self):
        stand = Stand()
        h = stand.history
        label(stand, h.A)
        stand.set_head(h.B)
        stand.queue_event("schedule", {}, refresh=True)
        entry = stand.queued()["entries"][0]
        self.assertEqual((entry["head"], entry["unapproved"][0]["by"]), (h.A, "unknown"))

    def test_rebase_with_the_same_patch_ids_is_carried_over(self):
        stand = Stand()
        h = stand.history
        self.assertEqual(patchids.own_patch_ids(h.git_dir, h.A, "main"), patchids.own_patch_ids(h.git_dir, h.R, "main"))
        label(stand, h.A)
        push(stand, h.A, h.R, sender="Celegans12")
        entry = stand.queued()["entries"][0]
        self.assertEqual((entry["head"], entry["approval"]["via"], entry["approval"]["from"], entry["earlier"]), (h.R, "carried", h.A, [h.A]))
        self.assertIn("same 1 patch-id", entry["approval"]["reason"])

    def test_rebase_that_edits_the_change_is_not(self):
        stand = Stand()
        h = stand.history
        label(stand, h.A)
        push(stand, h.A, h.C, sender="Celegans12")
        self.assertEqual(stand.queued()["entries"][0]["head"], h.A)

    def test_push_by_a_collaborator_is_carried_over(self):
        stand = Stand()
        h = stand.history
        label(stand, h.A)
        push(stand, h.A, h.B, sender="collab")
        entry = stand.queued()["entries"][0]
        self.assertEqual((entry["head"], entry["approval"]["reason"]), (h.B, "pushed by @collab (COLLABORATOR)"))

    def test_push_by_the_author_is_not_even_when_a_collaborator(self):
        stand = Stand()
        h = stand.history
        stand.set_association("Celegans12", "COLLABORATOR")
        label(stand, h.A)
        push(stand, h.A, h.B, sender="Celegans12")
        self.assertEqual(stand.queued()["entries"][0]["head"], h.A)

    def test_a_maintainer_approves_the_new_head(self):
        stand = Stand()
        h = stand.history
        label(stand, h.A)
        push(stand, h.A, h.B)
        command(stand, f"/title-test sha={h.B[:10]}")
        entry = stand.queued()["entries"][0]
        self.assertEqual((entry["head"], entry["earlier"], entry["unapproved"]), (h.B, [h.A], []))


class Publish(unittest.TestCase):
    def queued_stand(self):
        stand = Stand()
        label(stand, stand.history.A)
        return stand

    def test_accepted_result_edits_the_queued_comment(self):
        stand = self.queued_stand()
        h = stand.history
        c, r = claim(h.A), result(h.A)
        report = stand.push({c[0]: c[1], r[0]: r[1]}, at=formats.parse_time("2026-10-21T13:00:00Z"))
        self.assertEqual((report["accepted"], report["refused"]), ([r[0]], []))
        self.assertEqual([x["action"] for x in stand.outbox_calls()], ["new", "edit"])
        body = stand.bodies()[-1]
        self.assertIn("| laptop | NVIDIA GeForce RTX 5060 Laptop GPU, NVIDIA 615.71.09, Linux 7.2.8 | Grand Theft Auto V (PPSA04263) | rendering / rendering |", body)
        self.assertIn("| still wanted | 1 more machine: any hardware | any |", body)

    def refused(self, files, actor="CPritch", at="2026-10-21T13:00:00Z"):
        stand = self.queued_stand()
        files = files(stand.history)
        report = stand.push(dict(files), actor=actor, at=formats.parse_time(at))
        self.assertEqual(report["accepted"], [])
        self.assertTrue(report["refused"])
        self.assertEqual([x["action"] for x in stand.outbox_calls()], ["new"])
        return report

    def test_result_for_an_unapproved_head(self):
        report = self.refused(lambda h: [claim(h.B), result(h.B)])
        self.assertIn("not a head a maintainer approved", report["refused"][0][1])

    def test_result_after_the_claim_expired(self):
        report = self.refused(lambda h: [claim(h.A), result(h.A)], at="2026-10-21T15:00:01Z")
        self.assertIn("after its claim expired", report["refused"][0][1])

    def test_result_without_a_claim(self):
        self.refused(lambda h: [result(h.A)])

    def test_another_testers_machine(self):
        report = self.refused(lambda h: [claim(h.A, "desktop", "other"), result(h.A, "desktop", "other")], actor="CPritch")
        self.assertIn("may only add or change", report["refused"][0][1])

    def test_not_a_tester(self):
        self.refused(lambda h: [claim(h.A, tester="mallory"), result(h.A, tester="mallory")], actor="mallory")

    def test_a_push_that_touches_the_queue_is_refused_whole(self):
        report = self.refused(lambda h: [claim(h.A), result(h.A), ("queue.json", '{"format": 1, "entries": []}')])
        self.assertIn("queue.json", report["refused"][0][1])

    def test_a_queue_pushed_to_main_is_never_read(self):
        stand = self.queued_stand()
        h = stand.history
        forged = stand.queued()
        forged["entries"][0].update(head=h.B, job=formats.job_id(8104, h.B))
        first = stand.push({"queue.json": forged}, at=formats.parse_time("2026-10-21T13:00:00Z"))
        self.assertIn("queue.json", first["refused"][0][1])
        c, r = claim(h.B), result(h.B)
        second = stand.push({c[0]: c[1], r[0]: r[1]}, at=formats.parse_time("2026-10-21T13:00:00Z"))
        self.assertEqual(second["accepted"], [])
        self.assertIn("not a head a maintainer approved", second["refused"][0][1])

    def test_markup_in_a_result(self):
        def files(h):
            path, data = result(h.A)
            data["machine_line"] = "<script>"
            return [claim(h.A), (path, data)]
        self.refused(files)

    def test_tester_trust_result_is_shown_apart(self):
        stand = self.queued_stand()
        h = stand.history
        stand.set_head(h.B)
        c, r = claim(h.B), result(h.B, trust="tester")
        report = stand.push({c[0]: c[1], r[0]: r[1]}, at=formats.parse_time("2026-10-21T13:00:00Z"))
        self.assertEqual(report["accepted"], [r[0]])
        self.assertIn(f"**Run on the tester's trust** (`{h.B[:9]}`, not approved by a maintainer)", stand.bodies()[-1])


class CommandLine(unittest.TestCase):
    """The workflows' steps, run as the workflows run them: title-runs relay queue|publish with --forge fake."""

    def run_relay(self, stand, *args):
        import subprocess
        from title_runs import ROOT
        spec = f"fake:{stand.state}:{stand.outbox}"
        return subprocess.run(["python3", "-I", str(ROOT / "title-runs"), "relay", *args, "--forge", spec], capture_output=True, text=True)

    def test_queue_and_publish_steps(self):
        import json
        stand = Stand()
        h = stand.history
        payload = stand.root / "event.json"
        payload.write_text(json.dumps({"client_payload": {"event": "pull_request", "payload": event("labeled", HEAD=h.A, SENDER="CPritch")}}))
        done = self.run_relay(stand, "queue", "--state", str(stand.state_dir), "--data", str(stand.checkout), "--event-name", "repository_dispatch",
                              "--event-file", str(payload), "--anyps5-git", str(h.git_dir), "--main-ref", "main")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(stand.queued()["entries"][0]["head"], h.A)
        from relay_helpers import git, write
        before = git(stand.checkout, "rev-parse", "HEAD")
        for path, data in (claim(h.A, claimed=formats.iso(formats.now())), result(h.A)):
            write(stand.checkout, path, json.dumps(data))
        git(stand.checkout, "add", "-A")
        git(stand.checkout, "commit", "-qm", "laptop")
        after = git(stand.checkout, "rev-parse", "HEAD")
        done = self.run_relay(stand, "publish", "--state", str(stand.state_dir), "--data", str(stand.checkout), "--actor", "CPritch",
                              "--before", before, "--after", after)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual([c["action"] for c in stand.outbox_calls()], ["new", "edit"])


class NewOrEdit(unittest.TestCase):
    def first(self):
        stand = Stand()
        h = stand.history
        label(stand, h.A)
        c, r = claim(h.A), result(h.A)
        stand.push({c[0]: c[1], r[0]: r[1]}, at=formats.parse_time("2026-10-21T13:00:00Z"))
        push(stand, h.A, h.R)  # carried over: same patch-ids
        return stand

    def test_second_head_with_the_same_outcome_edits(self):
        stand = self.first()
        h = stand.history
        c, r = claim(h.R, claimed="2026-10-21T14:00:00Z"), result(h.R)
        stand.push({c[0]: c[1], r[0]: r[1]}, at=formats.parse_time("2026-10-21T15:00:00Z"))
        self.assertEqual(stand.outbox_calls()[-1]["action"], "edit")
        body = stand.bodies()[-1]
        self.assertIn(f"Title runs for `{h.R[:9]}`", body)
        self.assertIn(f"Carried over from `{h.A[:9]}`", body)
        self.assertIn("<details><summary>Earlier heads</summary>", body)
        self.assertIn(f"| `{h.A[:9]}` laptop |", body)

    def test_outcome_change_posts_a_new_comment(self):
        stand = self.first()
        h = stand.history
        c, r = claim(h.R, claimed="2026-10-21T14:00:00Z"), result(h.R, outcome_b="crashed (exit 139)", verdict="not enough counted runs")
        r[1]["titles"]["PPSA04263"]["verdict"] = {"verdict": "not enough counted runs", "diff": None}
        stand.push({c[0]: c[1], r[0]: r[1]}, at=formats.parse_time("2026-10-21T15:00:00Z"))
        self.assertEqual(stand.outbox_calls()[-1]["action"], "new")

    def test_verdict_flip_posts_a_new_comment(self):
        stand = self.first()
        h = stand.history
        c, r = claim(h.R, claimed="2026-10-21T14:00:00Z"), result(h.R, verdict="faster", diff=-7.0)
        stand.push({c[0]: c[1], r[0]: r[1]}, at=formats.parse_time("2026-10-21T15:00:00Z"))
        self.assertEqual(stand.outbox_calls()[-1]["action"], "new")


if __name__ == "__main__":
    unittest.main()
