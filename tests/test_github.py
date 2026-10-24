"""Reading GitHub with the optional sign-in (gh.py): the token goes with every read when there is one, only to GitHub's
API; it is kept readable only by the tester; a token GitHub doesn't take says so; signing in and out from the engine,
Settings and the command line; and the limit's notice suggests signing in."""

import datetime
import io
import json
import os
import stat
import unittest
from contextlib import redirect_stdout
from unittest import mock

import helpers  # noqa: F401
from helpers import make_config

from title_runs import cli, configfile, engine as engines, gh

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
try:
    from PySide6.QtWidgets import QApplication
except ImportError:
    QApplication = None


class Answer(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


def answering(sent, body):
    def urlopen(request, timeout=None):
        sent.append(request)
        return Answer(json.dumps(body).encode())
    return urlopen


class Token(unittest.TestCase):
    def test_sent_only_when_signed_in_and_only_to_the_api(self):
        sent = []
        with mock.patch("urllib.request.urlopen", answering(sent, {"title": "t"})):
            gh.GitHubRepo("boykopovar/AnyPS5").call("/repos/boykopovar/AnyPS5/pulls/1")
            gh.GitHubRepo("boykopovar/AnyPS5", "ghp_secret").call("/repos/boykopovar/AnyPS5/pulls/1")
        self.assertIsNone(sent[0].get_header("Authorization"))
        self.assertEqual(sent[1].get_header("Authorization"), "Bearer ghp_secret")
        self.assertTrue(all(request.full_url.startswith("https://api.github.com/") for request in sent))

    def test_kept_readable_only_by_the_tester(self):
        state = make_config().state_dir
        self.assertEqual(gh.read_token(state), "")
        gh.save_token(state, "  ghp_secret\n")
        self.assertEqual(gh.read_token(state), "ghp_secret")
        self.assertEqual(stat.S_IMODE(gh.token_path(state).stat().st_mode), 0o600)
        gh.save_token(state, "ghp_other")  # replaced whole
        self.assertEqual(gh.read_token(state), "ghp_other")
        gh.forget_token(state)
        gh.forget_token(state)  # forgetting twice is fine
        self.assertEqual(gh.read_token(state), "")

    def test_a_token_github_doesnt_take(self):
        import urllib.error
        error = urllib.error.HTTPError("https://api.github.com/user", 401, "Bad credentials", {}, io.BytesIO(b"{}"))
        with mock.patch("urllib.request.urlopen", side_effect=error), self.assertRaisesRegex(gh.GitHubError, "didn't take the token"):
            gh.signed_in_as("ghp_wrong")


class Engine(unittest.TestCase):
    def setUp(self):
        self.config = make_config(local_repository="boykopovar/AnyPS5", local_prs=[4287])
        configfile.save(self.config)
        self.engine = engines.Engine(self.config)

    def test_sign_in_and_out(self):
        self.engine.github_wait = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=40)
        self.assertIn("Signing in to GitHub (Settings, GitHub) raises the limit", self.engine.local_notice())
        with mock.patch("title_runs.gh.signed_in_as", return_value=("CPritch", 5000)) as asked:
            self.assertEqual(self.engine.sign_in(" ghp_secret "), ("CPritch", 5000))
            self.assertEqual(self.engine.github(), {"login": "CPritch", "limit": 5000})
        self.assertEqual(asked.call_count, 1)  # GitHub is asked once, then the answer is kept
        self.assertIsNone(self.engine.github_wait)  # the new limit starts now
        self.assertEqual(gh.read_token(self.config.state_dir), "ghp_secret")
        self.assertNotIn("ghp_secret", self.config.path.read_text())  # never in the config file
        self.engine.sign_out()
        self.assertEqual((self.engine.github(), gh.read_token(self.config.state_dir)), ({}, ""))

    def test_a_kept_token_github_no_longer_takes(self):
        gh.save_token(self.config.state_dir, "ghp_revoked")
        with mock.patch("title_runs.gh.signed_in_as", side_effect=gh.GitHubError("GitHub didn't take the token")) as asked:
            self.assertEqual(self.engine.github(), {"error": "GitHub didn't take the token"})
            self.engine.github()
        self.assertEqual(asked.call_count, 1)  # not asked again on every refresh

    def test_the_command_line(self):
        out = io.StringIO()
        with mock.patch("sys.stdin", io.StringIO("ghp_secret\n")), mock.patch("title_runs.gh.signed_in_as", return_value=("CPritch", 5000)), \
                redirect_stdout(out):
            code = cli.main(["--config", str(self.config.path), "github", "sign-in"])
        self.assertEqual((code, out.getvalue().strip()), (0, "Signed in to GitHub as CPritch: 5,000 reads an hour."))
        self.assertEqual(gh.read_token(self.config.state_dir), "ghp_secret")
        with redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(["--config", str(self.config.path), "github", "sign-out"]), 0)
        self.assertEqual(gh.read_token(self.config.state_dir), "")


@unittest.skipIf(QApplication is None, "PySide6 is not installed")
class Settings(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_sign_in_and_out_in_settings(self):
        from title_runs.ui import app
        from title_runs.ui.window import SettingsTab
        config = make_config()
        configfile.save(config)
        engine = app.Engine(config)
        tab = SettingsTab(engine)
        tab.refresh()
        self.assertEqual(tab.github_state.text(), "Not signed in: 60 reads an hour.")
        self.assertTrue(tab.sign_out.isHidden())
        tab.token.setText("ghp_secret")
        with mock.patch("title_runs.gh.signed_in_as", return_value=("CPritch", 5000)):
            tab.sign_in.click()
        self.assertEqual(tab.github_state.text(), "Signed in as <b>CPritch</b>: 5,000 reads an hour.")
        self.assertEqual(tab.token.text(), "")
        tab.sign_out.click()
        self.assertEqual(tab.github_state.text(), "Not signed in: 60 reads an hour.")
        with mock.patch("title_runs.gh.signed_in_as", side_effect=gh.GitHubError("GitHub didn't take the token")):
            tab.token.setText("ghp_wrong")
            tab.sign_in.click()
        self.assertEqual(tab.github_state.text(), "<b>Not signed in</b>: GitHub didn't take the token.")
        self.assertEqual(gh.read_token(config.state_dir), "")


if __name__ == "__main__":
    unittest.main()
