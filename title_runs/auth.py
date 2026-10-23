"""Signing in through the App's device flow: the tester types a code at github.com/login/device, and the client polls
until GitHub hands it a user access token.

The tool reads the project's pull requests with the token (GitHub allows 60 requests an hour without one). The token
can do only what both the tester and the App can, and the App needs no permissions to read public repositories, so
it can't write anything. It lasts 8 hours and is refreshed with the refresh token (6 months) without the App's
secret, which a device-flow token does not need. Kept in the client's state directory (mode 0600).
"""

import datetime
import json
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path

from . import gh, locks

DEVICE_URL = "https://github.com/login/device/code"
TOKEN_URL = "https://github.com/login/oauth/access_token"
GRANT = "urn:ietf:params:oauth:grant-type:device_code"


class AuthError(RuntimeError):
    pass


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


class DeviceFlow:
    def __init__(self, client_id, token_file):
        self.client_id, self.token_file = client_id, Path(token_file)

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
        """The stored sign-in, if it was made through this App: a config that names another App needs a new sign-in."""
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
        if self.expiring(data):
            with locks.held(self.token_file):  # GitHub replaces the refresh token: only one process may use it
                data = self.stored_for_this_app()  # another process may have refreshed it meanwhile
                if not data:
                    return None
                if self.expiring(data):
                    data = self.refresh(data)
        return data["access_token"]

    @staticmethod
    def expiring(data):
        expires = data.get("expires_at")
        return bool(expires and datetime.datetime.fromisoformat(expires) - _now() < datetime.timedelta(minutes=10) and data.get("refresh_token"))

    # -- the flow ------------------------------------------------------------------------------------------------------

    def _post(self, url, fields):
        request = urllib.request.Request(url, data=urllib.parse.urlencode(fields).encode(), method="POST", headers={"Accept": "application/json"})
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read())

    def start(self):
        """{"device_code", "user_code", "verification_uri", "interval", "expires_in"}."""
        return self._post(DEVICE_URL, {"client_id": self.client_id})

    def poll(self, device):
        """One poll: the stored token data once the tester has entered the code, None while pending."""
        reply = self._post(TOKEN_URL, {"client_id": self.client_id, "device_code": device["device_code"], "grant_type": GRANT})
        error = reply.get("error")
        if error in ("authorization_pending", "slow_down"):
            if error == "slow_down":
                # GitHub adds 5 s each time and counts from the last request: polling at the old pace gets slow_down for
                # ever. The caller waits interval() before the next poll.
                device["interval"] = int(reply.get("interval") or device.get("interval", 5) + 5)
            return None
        if error:
            raise AuthError(f"sign-in failed: {error} ({reply.get('error_description', '')})")
        login = gh.GitHubRepo("", token=reply["access_token"]).login()
        data = {**self.data(reply, login), "client_id": self.client_id}
        self.store(data)
        return data

    @staticmethod
    def interval(device):
        """Seconds to wait before the next poll: GitHub's interval and a second's margin, since a poll that comes even a
        little early gets slow_down."""
        return int(device.get("interval", 5)) + 1

    def wait(self, device, timeout=900, sleep=time.sleep):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            sleep(self.interval(device))
            data = self.poll(device)
            if data:
                return data
        raise AuthError("the device code expired before it was entered")

    def refresh(self, data):
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
