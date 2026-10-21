"""The App from a manifest (title_runs/app.py): the manifest's permissions and no webhook; create's page carries the
manifest and a state; a redirect with another state saves nothing; the right one saves the private key (0600) and
app.json without the client secret or the webhook secret, and fills the results repository's config.json."""

import json
import re
import stat
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

import helpers  # noqa: F401

from title_runs import app, export

CONVERTED = {"id": 123456, "slug": "title-runs-dev", "client_id": "Iv23liEXAMPLE", "client_secret": "SECRET-NOT-KEPT", "webhook_secret": None,
             "pem": "-----BEGIN RSA PRIVATE KEY-----\nnot a real key\n-----END RSA PRIVATE KEY-----\n", "owner": {"login": "CPritch"},
             "html_url": "https://github.com/apps/title-runs-dev", "permissions": dict(app.PERMISSIONS)}


class Manifest(unittest.TestCase):
    def test_permissions_no_webhook_private(self):
        m = app.manifest("title-runs-dev", "CPritch/AnyPS5", "CPritch/anyps5-title-runs-results", "CPritch/anyps5-title-runs")
        self.assertEqual(m["default_permissions"], {"actions": "read", "issues": "write", "pull_requests": "write", "metadata": "read"})
        self.assertEqual((m["hook_attributes"]["active"], m["default_events"], m["public"]), (False, [], False))
        self.assertEqual(m["url"], "https://github.com/CPritch/anyps5-title-runs")


class Create(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.repo = export.export(self.root / "results", "CPritch/AnyPS5", "CPritch/anyps5-title-runs-results", ["CPritch"],
                                  tool={"repository": "CPritch/anyps5-title-runs", "commit": "a" * 40})
        export.commit(self.repo)
        self.codes = []
        self.lines = []
        self.thread = threading.Thread(target=self.serve, daemon=True)
        self.thread.start()
        for _ in range(100):
            if self.lines:
                break
            threading.Event().wait(0.05)
        self.base = re.search(r"http://127\.0\.0\.1:\d+/", self.lines[0]).group(0)

    def serve(self):
        def exchange(code):
            self.codes.append(code)
            return CONVERTED
        try:
            self.record = app.create(self.root / "secret", "title-runs-dev", "CPritch/AnyPS5", "CPritch/anyps5-title-runs-results",
                                     "CPritch/anyps5-title-runs", results_repo=self.repo, open_browser=False, exchange=exchange, log=self.lines.append)
        except Exception as error:  # noqa: BLE001
            self.error = error

    def get(self, path):
        try:
            with urllib.request.urlopen(self.base + path.lstrip("/"), timeout=10) as response:
                return response.status, response.read().decode()
        except urllib.error.HTTPError as error:
            with error:
                return error.code, error.read().decode()

    def test_the_page_a_wrong_state_and_the_redirect(self):
        status, body = self.get("/")
        self.assertEqual(status, 200)
        state = re.search(r"settings/apps/new\?state=([\w-]+)", body).group(1)
        manifest = json.loads(re.search(r"name='manifest' value='([^']*)'", body).group(1).replace("&quot;", '"').replace("&amp;", "&"))
        self.assertEqual(manifest["redirect_url"], self.base + "done")
        self.assertEqual(self.get("/done?code=c1&state=forged")[0], 400)
        self.assertEqual((self.codes, (self.root / "secret").exists()), ([], False))
        status, body = self.get(f"/done?code=c2&state={state}")
        self.assertEqual(status, 200)
        self.assertIn("Enable Device Flow", body)
        self.assertIn("https://github.com/apps/title-runs-dev/installations/new", body)
        self.thread.join(10)
        key = self.root / "secret" / "title-runs-dev.private-key.pem"
        self.assertEqual(stat.S_IMODE(key.stat().st_mode), 0o600)
        saved = (self.root / "secret" / "app.json").read_text()
        self.assertNotIn("SECRET-NOT-KEPT", saved)
        self.assertEqual(json.loads(saved)["bot"], "title-runs-dev[bot]")
        config = json.loads((self.repo / "config.json").read_text())
        self.assertEqual(config["app"], {"id": 123456, "client_id": "Iv23liEXAMPLE", "bot": "title-runs-dev[bot]"})
        self.assertNotIn("BEGIN", "".join(p.read_text() for p in self.repo.rglob("*") if p.is_file() and ".git" not in p.parts))


if __name__ == "__main__":
    unittest.main()
