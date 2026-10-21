"""Signing in through the App's device flow (DESIGN.md, "Pieces": testers sign in themselves).

The tester types a code at github.com/login/device; the client polls until GitHub hands it a user access token. The
token can do only what both the tester and the App can (comment and open issues in the results repository). It lasts
8 hours and is refreshed with the refresh token (6 months) without the App's secret, which a device-flow token does
not need. Kept in the client's state directory (mode 0600).

endpoint "github" talks to github.com; "standin:<github.json>" to the stand-in (gh.FakeGitHub), where
`title-runs standin authorize <code> --as <login>` plays the tester typing the code.
"""

import datetime
import json
import os
import secrets
import time
import urllib.parse
import urllib.request
from pathlib import Path

from . import gh

DEVICE_URL = "https://github.com/login/device/code"
TOKEN_URL = "https://github.com/login/oauth/access_token"
GRANT = "urn:ietf:params:oauth:grant-type:device_code"


class AuthError(RuntimeError):
    pass


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


class DeviceFlow:
    def __init__(self, client_id, token_file, endpoint="github"):
        self.client_id, self.token_file, self.endpoint = client_id, Path(token_file), endpoint

    # -- the stored token ----------------------------------------------------------------------------------------------

    def stored(self):
        try:
            return json.loads(self.token_file.read_text())
        except (OSError, ValueError):
            return None

    def store(self, data):
        self.token_file.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.token_file.with_suffix(".tmp")
        temporary.write_text(json.dumps(data, indent=1))
        temporary.chmod(0o600)
        os.replace(temporary, self.token_file)

    def stored_for_this_app(self):
        """The stored sign-in, if it was made through this App: a results repository that names another App (one moved to
        a maintainer's account) needs a new sign-in."""
        data = self.stored()
        if data and data.get("client_id") != self.client_id:  # a sign-in kept before tokens named their App counts as another's
            return None
        return data

    def login(self):
        data = self.stored_for_this_app()
        return data.get("login") if data else None

    def sign_out(self):
        self.token_file.unlink(missing_ok=True)

    def token(self):
        """A valid access token (refreshed when it is about to expire), or None when not signed in."""
        data = self.stored_for_this_app()
        if not data:
            return None
        expires = data.get("expires_at")
        if expires and datetime.datetime.fromisoformat(expires) - _now() < datetime.timedelta(minutes=10) and data.get("refresh_token"):
            data = self.refresh(data)
        return data["access_token"]

    # -- the flow ------------------------------------------------------------------------------------------------------

    def _post(self, url, fields):
        request = urllib.request.Request(url, data=urllib.parse.urlencode(fields).encode(), method="POST", headers={"Accept": "application/json"})
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read())

    def start(self):
        """{"device_code", "user_code", "verification_uri", "interval", "expires_in"}."""
        if self.endpoint.startswith("standin:"):
            fake = gh.FakeGitHub(self.endpoint.split(":", 1)[1])
            letters = "BCDFGHJKLMNPQRSTVWXZ"  # GitHub's codes look like WDJB-MJHT
            code = "-".join("".join(secrets.choice(letters) for _ in range(4)) for _ in range(2))
            device = secrets.token_hex(8)
            fake.data.setdefault("device", {})[device] = {"user_code": code, "client_id": self.client_id, "login": None}
            fake.save()
            return {"device_code": device, "user_code": code, "verification_uri": "https://github.com/login/device", "interval": 1, "expires_in": 900}
        return self._post(DEVICE_URL, {"client_id": self.client_id})

    def poll(self, device):
        """One poll: the stored token data once the tester has entered the code, None while pending."""
        if self.endpoint.startswith("standin:"):
            fake = gh.FakeGitHub(self.endpoint.split(":", 1)[1])
            record = fake.data.get("device", {}).get(device["device_code"])
            if record is None:
                raise AuthError("the device code expired")
            if not record["login"]:
                return None
            token = f"standin-{record['login']}-{secrets.token_hex(4)}"
            fake.data.setdefault("tokens", {})[token] = record["login"]
            fake.save()
            reply = {"access_token": token, "expires_in": 28800, "refresh_token": f"r-{token}", "refresh_token_expires_in": 15897600}
            login = record["login"]
        else:
            reply = self._post(TOKEN_URL, {"client_id": self.client_id, "device_code": device["device_code"], "grant_type": GRANT})
            error = reply.get("error")
            if error in ("authorization_pending", "slow_down"):
                if error == "slow_down":
                    device["interval"] = device.get("interval", 5) + 5
                return None
            if error:
                raise AuthError(f"sign-in failed: {error} ({reply.get('error_description', '')})")
            login = gh.GitHubRepo("", token=reply["access_token"]).login()
        data = {**self.data(reply, login), "client_id": self.client_id}
        self.store(data)
        return data

    def wait(self, device, timeout=900, sleep=time.sleep):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            data = self.poll(device)
            if data:
                return data
            sleep(device.get("interval", 5))
        raise AuthError("the device code expired before it was entered")

    def refresh(self, data):
        if self.endpoint.startswith("standin:"):
            return data
        reply = self._post(TOKEN_URL, {"client_id": self.client_id, "grant_type": "refresh_token", "refresh_token": data["refresh_token"]})
        if reply.get("error"):
            raise AuthError(f"could not refresh the sign-in: {reply['error']}; sign in again")
        fresh = {**self.data(reply, data["login"]), "client_id": self.client_id}
        self.store(fresh)
        return fresh

    @staticmethod
    def data(reply, login):
        out = {"access_token": reply["access_token"], "login": login, "signed_in": _now().isoformat(timespec="seconds")}
        if reply.get("expires_in"):
            out["expires_at"] = (_now() + datetime.timedelta(seconds=int(reply["expires_in"]))).isoformat(timespec="seconds")
        if reply.get("refresh_token"):
            out["refresh_token"] = reply["refresh_token"]
        return out


def repo_as_tester(endpoint, repository, flow):
    """The results repository as the signed-in tester (gh.Repo)."""
    if endpoint.startswith("standin:"):
        login = flow.login()
        if not login:
            raise AuthError("not signed in")
        return gh.FakeGitHub.standin(endpoint.split(":", 1)[1]).as_(repository, login)
    token = flow.token()
    if not token:
        raise AuthError("not signed in")
    return gh.GitHubRepo(repository, token=token)
