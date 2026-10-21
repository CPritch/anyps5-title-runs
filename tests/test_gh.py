"""gh.GitHubRepo against GitHub's real response shapes (a stubbed call, no network): comments are read by creation
time, as the fake gives them, not by GitHub's since= (updated since), which brings back old comments edited later."""

import datetime
import unittest
from unittest import mock

import helpers  # noqa: F401

from title_runs import gh


def note(number, created, updated=None, body="hi", user="someone"):
    return {"id": number, "issue_url": "https://api.github.com/repos/o/r/issues/7", "body": body, "user": {"login": user},
            "author_association": "NONE", "created_at": created, "updated_at": updated or created}


class Comments(unittest.TestCase):
    def test_new_comments_only_oldest_first_and_paging_stops_at_since(self):
        start = datetime.datetime(2026, 10, 21, 16, 59, tzinfo=datetime.timezone.utc)
        page1 = [note(110 - i, (start - datetime.timedelta(minutes=i)).strftime("%Y-%m-%dT%H:%M:%SZ")) for i in range(100)]  # 16:59 to 15:20
        page2 = [note(10, "2026-10-21T15:10:00Z"), note(9, "2026-10-14T13:50:17Z", updated="2026-10-21T16:30:00Z")]  # an old one, edited
        calls = []

        def call(method, path, body=None, params=None):
            calls.append(params)
            return {1: page1, 2: page2}[params["page"]]

        repo = gh.GitHubRepo("o/r")
        with mock.patch.object(repo, "call", side_effect=call):
            out = repo.comments(since="2026-10-21T15:15:00Z")
        self.assertEqual(len(out), 100)
        self.assertEqual(out[0]["created_at"], "2026-10-21T15:20:00Z")
        self.assertNotIn(9, [c["id"] for c in out])
        self.assertEqual([c["page"] for c in calls], [1, 2])
        self.assertEqual((calls[0]["sort"], calls[0]["direction"]), ("created", "desc"))
        self.assertNotIn("since", calls[0])

    def test_an_edited_old_comment_is_not_new(self):
        repo = gh.GitHubRepo("o/r")
        with mock.patch.object(repo, "call", return_value=[note(2, "2026-10-21T16:00:00Z"), note(1, "2026-10-14T13:50:17Z", "2026-10-21T16:05:00Z")]):
            self.assertEqual([c["id"] for c in repo.comments(since="2026-10-21T15:00:00Z")], [2])


if __name__ == "__main__":
    unittest.main()


class DryRun(unittest.TestCase):
    def test_reads_go_through_and_writes_are_recorded(self):
        import json
        import tempfile
        from pathlib import Path
        outbox = Path(tempfile.mkdtemp()) / "outbox"
        inner = mock.Mock(repository="o/r")
        inner.pull.return_value = {"head": "a" * 40}
        dry = gh.DryRun(inner, outbox, "title-runs-dev[bot]")
        self.assertEqual(dry.pull(7)["head"], "a" * 40)
        number = dry.create_issue("Overview", "body", ["overview"])
        dry.remove_label(7, "title-test")
        self.assertFalse(inner.create_issue.called or inner.remove_label.called)
        files = sorted(p.name for p in outbox.iterdir())
        self.assertEqual(files, ["001-title-runs-devbot-create-issue.json", "001-title-runs-devbot-create-issue.md", "002-title-runs-devbot-remove-label.json"])
        self.assertEqual(json.loads((outbox / files[0]).read_text())["number"], number)

    def test_an_absent_repository_reads_empty(self):
        import tempfile
        dry = gh.DryRun(None, tempfile.mkdtemp(), "github-actions[bot]", "o/results")
        self.assertEqual((dry.issues(), dry.comments(since="x"), dry.label_actor(1, "approved")), ([], [], None))
