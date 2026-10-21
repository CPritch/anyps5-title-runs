"""title-runs app manifest|create: the GitHub App for title runs, made from a manifest (DESIGN.md, "Pieces").

`manifest` prints the App's manifest. `create` serves a page on 127.0.0.1 that sends the manifest to GitHub; the owner
presses "Create GitHub App" there, and GitHub sends the browser back with a code. The code is exchanged, without a
token, for the App (POST /app-manifests/{code}/conversions). The private key goes to OUT/<slug>.private-key.pem (mode
0600) and the App's ID, client ID, slug and bot name to OUT/app.json. The client secret and the webhook secret it also
returns are not kept: the device flow needs only the client ID, and the App has no webhook. With --results-repo, the
App's ID, client ID and bot name are written into that results repository's config.json and committed.

Two settings a manifest cannot carry are left for the owner: the device flow (the App's settings, "Identifying and
authorizing users", Enable Device Flow) and the installation. The last page links to both.
"""

import html
import http.server
import json
import os
import secrets
import subprocess
import threading
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path

from . import formats

# What the relay needs (DESIGN.md, "Checked against GitHub's documentation"): labels and comments on AnyPS5's PRs and
# reactions to commands (Issues and Pull requests, write), the PRs' workflow runs to time a head (Actions, read), the
# collaborator check (Metadata, read). Testers' sign-ins act through the same permissions in the results repository:
# registration issues and comments (Issues, write).
PERMISSIONS = {"actions": "read", "issues": "write", "pull_requests": "write", "metadata": "read"}
CONVERSIONS = "https://api.github.com/app-manifests/{code}/conversions"


def manifest(name, anyps5, results, tool, redirect_url=None):
    data = {
        "name": name,
        "url": f"https://github.com/{tool}",
        "description": (f"AnyPS5 title runs: queues {anyps5} pull requests a maintainer labels title-test, and carries testers' "
                        f"results to them through {results}. No webhook; its workflow polls."),
        "public": False,
        "hook_attributes": {"url": f"https://github.com/{results}", "active": False},
        "default_permissions": dict(PERMISSIONS),
        "default_events": [],
        "request_oauth_on_install": False,
    }
    if redirect_url:
        data["redirect_url"] = redirect_url
    return data


def convert(code):
    request = urllib.request.Request(CONVERSIONS.format(code=urllib.parse.quote(code)), data=b"", method="POST",
                                     headers={"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read())


def save(out, data):
    """The private key (0600) and app.json; never the client secret or the webhook secret."""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    key = out / f"{data['slug']}.private-key.pem"
    descriptor = os.open(key, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        stream.write(data["pem"])
    record = {"id": data["id"], "client_id": data["client_id"], "slug": data["slug"], "bot": f"{data['slug']}[bot]",
              "owner": (data.get("owner") or {}).get("login", ""), "html_url": data.get("html_url", ""), "private_key": str(key),
              "permissions": data.get("permissions", {}), "created": formats.iso(formats.now())}
    (out / "app.json").write_text(json.dumps(record, indent=2) + "\n")
    return record


def fill_results_repo(repo_dir, record):
    """Write the App into a results repository's config.json and commit it there."""
    path = Path(repo_dir) / "config.json"
    config = json.loads(path.read_text())
    config["app"] = {"id": record["id"], "client_id": record["client_id"], "bot": record["bot"]}
    formats.check_config(config)
    path.write_text(json.dumps(config, indent=2) + "\n")
    if (Path(repo_dir) / ".git").exists():
        subprocess.run(["git", "-C", str(repo_dir), "add", "config.json"], check=True)
        subprocess.run(["git", "-C", str(repo_dir), "commit", "-q", "-m", f"config.json: the App {record['slug']} ({record['id']})"], check=True)


def page(title, body):
    return (f"<!doctype html><meta charset='utf-8'><title>{html.escape(title)}</title>"
            f"<body style='font: 16px/1.5 system-ui, sans-serif; max-width: 46em; margin: 3em auto; padding: 0 1em'>"
            f"<h1 style='font-size: 1.4em'>{html.escape(title)}</h1>{body}</body>").encode()


def create(out, name, anyps5, results, tool, port=0, results_repo=None, open_browser=True, exchange=convert, organization=None, log=print):
    """Serve the manifest page and wait for GitHub's redirect; returns app.json's record."""
    state = secrets.token_urlsafe(24)
    done = threading.Event()
    outcome = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, status, content):
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(content)

        def do_GET(self):  # noqa: N802
            url = urllib.parse.urlparse(self.path)
            query = urllib.parse.parse_qs(url.query)
            if url.path == "/":
                target = (f"https://github.com/organizations/{organization}/settings/apps/new" if organization
                          else "https://github.com/settings/apps/new") + f"?state={state}"
                body = json.dumps(manifest(name, anyps5, results, tool, f"http://127.0.0.1:{server.server_port}/done"))
                perms = ", ".join(f"{k.replace('_', ' ')} {v}" for k, v in PERMISSIONS.items())
                return self.reply(200, page(f"Create the GitHub App {name}", (
                    f"<p>This sends the App's manifest to GitHub: {html.escape(perms)}; no webhook; only installable on this account. "
                    f"GitHub shows it before anything is created; press <b>Create GitHub App</b> there.</p>"
                    f"<form action='{html.escape(target)}' method='post'><input type='hidden' name='manifest' value='{html.escape(body, quote=True)}'>"
                    f"<button style='font-size: 1.1em; padding: .5em 1em'>Continue to GitHub</button></form>"
                    f"<details><summary>The manifest</summary><pre>{html.escape(json.dumps(json.loads(body), indent=2))}</pre></details>")))
            if url.path == "/done":
                if query.get("state", [""])[0] != state or not query.get("code"):
                    return self.reply(400, page("Not from this request", "<p>The state does not match the page this server sent. Nothing was saved.</p>"))
                try:
                    record = save(out, exchange(query["code"][0]))
                    if results_repo:
                        fill_results_repo(results_repo, record)
                except Exception as error:  # noqa: BLE001  (shown on the page and in the terminal)
                    outcome["error"] = str(error)
                    self.reply(500, page("The App was not saved", f"<p>{html.escape(str(error))}</p>"))
                    done.set()
                    return
                outcome["record"] = record
                slug = html.escape(record["slug"])
                self.reply(200, page(f"Created {record['slug']}", (
                    f"<p>App ID {record['id']}, client ID <code>{html.escape(record['client_id'])}</code>. The private key is in "
                    f"<code>{html.escape(record['private_key'])}</code> (only this computer has it).</p><ol>"
                    f"<li><a href='https://github.com/settings/apps/{slug}'>Open its settings</a>, tick <b>Enable Device Flow</b> under "
                    f"\"Identifying and authorizing users\", and press <b>Save changes</b>.</li>"
                    f"<li><a href='https://github.com/apps/{slug}/installations/new'>Install it</a>: <b>Only select repositories</b>, "
                    f"then {html.escape(anyps5)} and {html.escape(results)}.</li></ol><p>You can close this page.</p>")))
                done.set()
                return
            self.reply(404, page("Not here", ""))

    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    address = f"http://127.0.0.1:{server.server_port}/"
    log(f"Open {address} to create the App (waiting for GitHub to send the browser back)")
    if open_browser:
        webbrowser.open(address)
    try:
        done.wait()
    finally:
        server.shutdown()
        server.server_close()
    if "error" in outcome:
        raise RuntimeError(outcome["error"])
    log(f"created {outcome['record']['slug']} ({outcome['record']['id']}); app.json and the private key are in {out}")
    return outcome["record"]
