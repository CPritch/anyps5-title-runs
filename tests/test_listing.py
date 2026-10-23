"""The pull requests listing (listing.py) behind All pull requests: every open pull request, read on Refresh in place of
what was listed, a listing from before 2026-10-23 read again; and a PR's "Unblocks:" line (rules.unblocks)."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from helpers import make_pr

from title_runs import listing as listings, rules


def repo(*prs):
    fake = mock.Mock()
    fake.repository = "boykopovar/AnyPS5"
    fake.pages.return_value = list(prs)
    return fake


class Listing(unittest.TestCase):
    def setUp(self):
        self.path = Path(tempfile.mkdtemp()) / "listing.json"

    def test_every_open_pull_request_in_place_of_what_was_listed(self):
        listing = listings.Listing(self.path)
        github = repo(make_pr(1, "a1", body="- [x] Unblocks: PPSA04263", labels=["perf"]), make_pr(2, "b1", draft=True))
        self.assertEqual(listing.refresh(github), 2)
        self.assertEqual(github.pages.call_args.args[:2], ("/repos/boykopovar/AnyPS5/pulls", {"state": "open", "sort": "updated", "direction": "desc"}))
        self.assertEqual(listing.get(1), {"number": 1, "title": "PR 1", "author": "alice", "head": "a1", "draft": False, "labels": ["perf"],
                                          "body": "- [x] Unblocks: PPSA04263", "updated": "2026-10-20T10:00:00Z"})
        listing.refresh(repo(make_pr(3, "c1")))  # 1 and 2 closed since
        self.assertEqual([pr["number"] for pr in listing.open()], [3])
        self.assertEqual(listings.Listing(self.path).get(3)["head"], "c1")  # kept on disk
        self.assertTrue(listing.refreshed())

    def test_a_listing_from_before_is_read_again(self):
        self.path.write_text(json.dumps({"newest": "x", "prs": {"7": {"number": 7, "state": "OPEN", "headRefOid": "x"}}}))
        listing = listings.Listing(self.path)
        self.assertEqual((listing.open(), listing.refreshed()), ([], None))


class Unblocks(unittest.TestCase):
    def test_unblocks_line(self):
        body = "### Checklist\n- [x] Unblocks: PPSA04263 #3232, PPSA01325 <!-- e.g. PPSA00000 -->\n- [x] Depends on: none"
        self.assertEqual(rules.unblocks(body), {"PPSA04263", "PPSA01325"})
        self.assertEqual(rules.unblocks("- [ ] Unblocks: none"), set())


if __name__ == "__main__":
    unittest.main()
