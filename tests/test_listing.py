"""The pull requests listing (listing.py) behind All pull requests: the first refresh lists open PRs to the last page,
later ones stop at the newest cached update; and a PR's "Unblocks:" line (rules.unblocks)."""

import tempfile
import unittest
from pathlib import Path

from helpers import FakeClient, make_pr

from title_runs import listing as listings, rules


class Listing(unittest.TestCase):
    def setUp(self):
        self.path = Path(tempfile.mkdtemp()) / "listing.json"

    def test_first_refresh_lists_open_prs_until_the_last_page(self):
        client = FakeClient([([make_pr(1, "a1", "2026-10-20T10:00:00Z"), make_pr(2, "b1", "2026-10-20T09:00:00Z")], True),
                             ([make_pr(3, "c1", "2026-10-19T09:00:00Z")], False)])
        listing = listings.Listing(self.path)
        self.assertEqual(listing.refresh(client, "o", "r"), 2)
        self.assertEqual(client.calls[0]["states"], ["OPEN"])
        self.assertEqual(sorted(listing.data["prs"]), ["1", "2", "3"])
        self.assertEqual(listing.data["newest"], "2026-10-20T10:00:00Z")

    def test_later_refreshes_stop_at_the_newest_cached_update(self):
        listing = listings.Listing(self.path)
        listing.merge([make_pr(1, "a1", "2026-10-20T10:00:00Z")])
        client = FakeClient([([make_pr(1, "a2", "2026-10-20T11:00:00Z"), make_pr(4, "d1", "2026-10-20T09:00:00Z")], True),
                             ([make_pr(5, "e1", "2026-10-19T09:00:00Z")], False)])
        self.assertEqual(listing.refresh(client, "o", "r"), 1)
        self.assertIsNone(client.calls[0]["states"])
        self.assertEqual(listing.get(1)["headRefOid"], "a2")
        self.assertIsNone(listing.get(5))

    def test_the_cache_survives_a_restart(self):
        listing = listings.Listing(self.path)
        listing.merge([make_pr(7, "x", "2026-10-20T10:00:00Z")])
        listing.save()
        self.assertEqual(listings.Listing(self.path).get(7)["headRefOid"], "x")


class Unblocks(unittest.TestCase):
    def test_unblocks_line(self):
        body = "### Checklist\n- [x] Unblocks: PPSA04263 #3232, PPSA01325 <!-- e.g. PPSA00000 -->\n- [x] Depends on: none"
        self.assertEqual(rules.unblocks(body), {"PPSA04263", "PPSA01325"})
        self.assertEqual(rules.unblocks("- [ ] Unblocks: none"), set())


if __name__ == "__main__":
    unittest.main()
