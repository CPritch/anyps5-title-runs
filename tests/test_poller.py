import datetime
import tempfile
import unittest
from pathlib import Path

from helpers import FakeClient, at, make_config, make_pr

from title_runs import poller, rules
from title_runs.state import PAUSED, READY, SUPERSEDED, WAITING, State


class Listing(unittest.TestCase):
    def setUp(self):
        self.path = Path(tempfile.mkdtemp()) / "listing.json"

    def test_first_poll_lists_open_prs_until_the_last_page(self):
        client = FakeClient([([make_pr(1, "a1", "2026-10-20T10:00:00Z"), make_pr(2, "b1", "2026-10-20T09:00:00Z")], True),
                             ([make_pr(3, "c1", "2026-10-19T09:00:00Z")], False)])
        listing = poller.Listing(self.path)
        self.assertEqual(listing.refresh(client, "o", "r"), 2)
        self.assertEqual(client.calls[0]["states"], ["OPEN"])
        self.assertEqual(sorted(listing.data["prs"]), ["1", "2", "3"])
        self.assertEqual(listing.data["newest"], "2026-10-20T10:00:00Z")

    def test_later_polls_stop_at_the_newest_cached_update(self):
        listing = poller.Listing(self.path)
        listing.merge([make_pr(1, "a1", "2026-10-20T10:00:00Z")])
        client = FakeClient([([make_pr(1, "a2", "2026-10-20T11:00:00Z"), make_pr(4, "d1", "2026-10-20T09:00:00Z")], True),
                             ([make_pr(5, "e1", "2026-10-19T09:00:00Z")], False)])
        self.assertEqual(listing.refresh(client, "o", "r"), 1)
        self.assertIsNone(client.calls[0]["states"])
        self.assertEqual(listing.get(1)["headRefOid"], "a2")
        self.assertIsNone(listing.get(5))

    def test_the_cache_survives_a_restart(self):
        listing = poller.Listing(self.path)
        listing.merge([make_pr(7, "x", "2026-10-20T10:00:00Z")])
        listing.save()
        self.assertEqual(poller.Listing(self.path).get(7)["headRefOid"], "x")

    def test_followed_prs_are_read_directly(self):
        listing = poller.Listing(self.path)
        client = FakeClient(direct={10: make_pr(10, "z9")})
        listing.fetch(client, "o", "r", [10])
        self.assertEqual(listing.get(10)["headRefOid"], "z9")


class Follow(unittest.TestCase):
    def setUp(self):
        self.config = make_config()

    def test_unblocks_line(self):
        body = "### Checklist\n- [x] Unblocks: PPSA04263 #3232, PPSA01325 <!-- e.g. PPSA00000 -->\n- [x] Depends on: none"
        self.assertEqual(rules.unblocks(body), {"PPSA04263", "PPSA01325"})
        self.assertEqual(rules.unblocks("- [ ] Unblocks: none"), set())

    def test_reasons(self):
        self.assertEqual(rules.followed(make_pr(10, "a"), self.config), "listed")
        self.assertEqual(rules.followed(make_pr(11, "a", body="- [x] Unblocks: PPSA04263 #1"), self.config), "unblocks PPSA04263")
        self.assertIsNone(rules.followed(make_pr(12, "a", body="- [x] Unblocks: PPSA99999 #1"), self.config))
        self.assertEqual(rules.followed(make_pr(13, "a", labels=["needs-title-run"]), self.config), "label needs-title-run")
        self.assertIsNone(rules.followed(make_pr(10, "a", state="MERGED"), self.config))
        self.assertIsNone(rules.followed(make_pr(10, "a", draft=True), self.config))

    def test_trust(self):
        self.assertTrue(rules.trusted(make_pr(1, "a", author="alice"), self.config)[0])
        self.assertFalse(rules.trusted(make_pr(1, "a", author="mallory"), self.config)[0])
        self.assertFalse(rules.trusted(make_pr(1, "a", author="alice", committer="mallory"), self.config)[0])
        self.assertTrue(rules.trusted(make_pr(1, "a", author="mallory", labels=["title-runs-ok"]), self.config)[0])


class Debounce(unittest.TestCase):
    def setUp(self):
        self.config = make_config()
        self.state = State(Path(tempfile.mkdtemp()) / "state.json")
        self.listing = poller.Listing(Path(tempfile.mkdtemp()) / "listing.json")

    def poll(self, pr, moment):
        self.listing.merge([pr])
        return poller.update(self.state, self.listing, self.config, at(moment))

    def test_a_new_head_waits_until_it_has_been_unchanged_for_the_debounce(self):
        events = self.poll(make_pr(10, "h1", committed="2026-10-20T11:59:00Z"), "2026-10-20T12:00")
        self.assertIn((10, "new-head", "h1"), events)
        self.assertEqual(self.state.current(10)["status"], WAITING)
        self.poll(make_pr(10, "h1", committed="2026-10-20T11:59:00Z"), "2026-10-20T12:05")
        self.assertEqual(self.state.current(10)["status"], WAITING)
        events = self.poll(make_pr(10, "h1", committed="2026-10-20T11:59:00Z"), "2026-10-20T12:09")
        self.assertEqual(self.state.current(10)["status"], READY)
        self.assertIn((10, "ready", "h1"), events)

    def test_an_old_head_on_the_first_poll_is_ready_at_once(self):
        self.poll(make_pr(10, "h1", committed="2026-10-19T08:00:00Z"), "2026-10-20T12:00")
        self.assertEqual(self.state.current(10)["status"], READY)

    def test_a_head_replaced_before_it_was_built_is_superseded(self):
        self.poll(make_pr(10, "h1", committed="2026-10-20T11:59:00Z"), "2026-10-20T12:00")
        events = self.poll(make_pr(10, "h2", committed="2026-10-20T12:04:00Z"), "2026-10-20T12:04")
        self.assertIn((10, "superseded", "h1"), events)
        heads = self.state.pr(10)["heads"]
        self.assertEqual([h["status"] for h in heads], [SUPERSEDED, WAITING])
        self.poll(make_pr(10, "h2"), "2026-10-20T12:10")
        self.assertEqual(self.state.current(10)["status"], WAITING)
        self.poll(make_pr(10, "h2"), "2026-10-20T12:14")
        self.assertEqual(self.state.current(10)["status"], READY)
        self.assertEqual(poller.ready(self.state), [(10, self.state.current(10))])

    def test_a_ready_head_replaced_is_superseded_too(self):
        self.poll(make_pr(10, "h1", committed="2026-10-19T08:00:00Z"), "2026-10-20T12:00")
        self.assertEqual(self.state.current(10)["status"], READY)
        self.poll(make_pr(10, "h2"), "2026-10-20T12:01")
        self.assertEqual(self.state.pr(10)["heads"][0]["status"], SUPERSEDED)

    def test_a_built_head_stays_done_when_a_new_one_arrives(self):
        self.poll(make_pr(10, "h1", committed="2026-10-19T08:00:00Z"), "2026-10-20T12:00")
        poller.finish(self.state, 10, "h1", "done", None)
        self.poll(make_pr(10, "h2"), "2026-10-20T13:00")
        self.assertEqual([h["status"] for h in self.state.pr(10)["heads"]], ["done", WAITING])


class Allowlist(unittest.TestCase):
    def setUp(self):
        self.config = make_config()
        self.state = State(Path(tempfile.mkdtemp()) / "state.json")
        self.listing = poller.Listing(Path(tempfile.mkdtemp()) / "listing.json")

    def test_an_author_not_on_the_list_pauses_until_the_tester_confirms(self):
        self.listing.merge([make_pr(10, "h1", author="mallory", committed="2026-10-19T08:00:00Z")])
        events = poller.update(self.state, self.listing, self.config, at("2026-10-20T12:00"))
        self.assertEqual(self.state.current(10)["status"], PAUSED)
        self.assertTrue(any(kind == "paused" and "mallory" in detail for _, kind, detail in events))
        self.assertEqual(poller.ready(self.state), [])
        poller.confirm(self.state, 10)
        self.assertEqual(self.state.current(10)["status"], READY)

    def test_a_confirmation_covers_only_that_head(self):
        self.listing.merge([make_pr(10, "h1", author="mallory", committed="2026-10-19T08:00:00Z")])
        poller.update(self.state, self.listing, self.config, at("2026-10-20T12:00"))
        poller.confirm(self.state, 10)
        self.listing.merge([make_pr(10, "h2", author="mallory", committed="2026-10-20T12:30:00Z")])
        poller.update(self.state, self.listing, self.config, at("2026-10-20T12:30"))
        poller.update(self.state, self.listing, self.config, at("2026-10-20T12:41"))
        self.assertEqual(self.state.current(10)["status"], PAUSED)

    def test_a_push_by_someone_else_on_a_trusted_authors_pr_pauses(self):
        self.listing.merge([make_pr(10, "h1", author="alice", committer="mallory", committed="2026-10-19T08:00:00Z")])
        poller.update(self.state, self.listing, self.config, at("2026-10-20T12:00"))
        self.assertEqual(self.state.current(10)["status"], PAUSED)
        self.assertIn("mallory", self.state.current(10)["trust"])


if __name__ == "__main__":
    unittest.main()
