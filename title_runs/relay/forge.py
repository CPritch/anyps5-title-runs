"""Everything the workflows ask of GitHub about AnyPS5, behind one interface (Forge), so the real App and a fake slot in.

GitHubForge calls the REST API with the App's installation token (the workflow gets it from
actions/create-github-app-token). FakeForge keeps a stand-in repository's pull requests, accounts and comments in a
JSON file and writes every call it is asked to make to an outbox, as the round-1 poster did: <n>-<action>.json with
the request, and the comment body beside it as .md.

The patch-ids that decide whether a push carries an approval over are computed from git objects (relay/patchids.py),
not through this interface: the workflow fetches AnyPS5's history, the stand-in has a local clone.
"""

import datetime
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

API = "https://api.github.com"
TRUSTED_ASSOCIATIONS = ("OWNER", "MEMBER", "COLLABORATOR")


class ForgeError(RuntimeError):
    pass


class Forge:
    """The calls the queue and publish workflows make. pull() returns {"number", "title", "author", "state" (open,
    closed, merged), "head"}; commits() the SHAs of the PR's commits; association() OWNER, MEMBER, COLLABORATOR,
    CONTRIBUTOR or NONE."""

    def pull(self, number):
        raise NotImplementedError

    def commits(self, number):
        raise NotImplementedError

    def association(self, login):
        raise NotImplementedError

    def react(self, comment_id, content):
        raise NotImplementedError

    def create_comment(self, number, body):
        raise NotImplementedError

    def edit_comment(self, comment_id, body):
        raise NotImplementedError


class GitHubForge(Forge):
    def __init__(self, repository, token_env="TITLE_RUNS_APP_TOKEN"):
        self.repository, self.token_env = repository, token_env

    def call(self, method, path, body=None):
        token = os.environ.get(self.token_env)
        if not token:
            raise ForgeError(f"no token in ${self.token_env}")
        request = urllib.request.Request(f"{API}{path}", data=json.dumps(body).encode() if body is not None else None, method=method,
                                         headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                                                  "X-GitHub-Api-Version": "2022-11-28", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return json.loads(response.read() or b"null")
        except urllib.error.HTTPError as error:
            raise ForgeError(f"{method} {path}: HTTP {error.code} {error.read()[:300]!r}") from error

    def pull(self, number):
        data = self.call("GET", f"/repos/{self.repository}/pulls/{number}")
        state = "merged" if data.get("merged_at") else data["state"]
        return {"number": number, "title": data["title"], "author": data["user"]["login"], "state": state, "head": data["head"]["sha"]}

    def commits(self, number):
        shas, page = [], 1
        while page <= 3:
            batch = self.call("GET", f"/repos/{self.repository}/pulls/{number}/commits?per_page=100&page={page}")
            shas += [c["sha"] for c in batch]
            if len(batch) < 100:
                break
            page += 1
        return shas

    def association(self, login):
        # The permission endpoint answers for collaborators; OWNER and MEMBER (organisation accounts) both come back as
        # admin or write, which the rules treat alike.
        try:
            data = self.call("GET", f"/repos/{self.repository}/collaborators/{login}/permission")
        except ForgeError:
            return "NONE"
        return "COLLABORATOR" if data.get("permission") in ("admin", "maintain", "write") else "NONE"

    def react(self, comment_id, content):
        self.call("POST", f"/repos/{self.repository}/issues/comments/{comment_id}/reactions", {"content": content})

    def create_comment(self, number, body):
        return self.call("POST", f"/repos/{self.repository}/issues/{number}/comments", {"body": body})["id"]

    def edit_comment(self, comment_id, body):
        self.call("PATCH", f"/repos/{self.repository}/issues/comments/{comment_id}", {"body": body})


class FakeForge(Forge):
    """A stand-in for AnyPS5 on GitHub: state.json {"repository", "pulls": {n: {...pull(), "commits": [...]}},
    "associations": {login: association}, "comments": {id: {"pr", "body"}}, "next_comment": n} and an outbox."""

    def __init__(self, state_file, outbox):
        self.state_file, self.outbox = Path(state_file), Path(outbox)
        self.data = json.loads(self.state_file.read_text())
        self.repository = self.data["repository"]

    def save(self):
        self.state_file.write_text(json.dumps(self.data, indent=2, sort_keys=True))

    def record(self, action, method, path, body=None, extra=None):
        self.outbox.mkdir(parents=True, exist_ok=True)
        number = len(list(self.outbox.glob("*.json"))) + 1
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        name = f"{number:03d}-{stamp}-{action}"
        request = {"method": method, "path": path, "json": {"body": f"<{name}.md>"} if body is not None else extra}
        (self.outbox / f"{name}.json").write_text(json.dumps({"action": action, "request": request, **(extra or {})}, indent=2))
        if body is not None:
            (self.outbox / f"{name}.md").write_text(body)
        return name

    def pull(self, number):
        entry = self.data["pulls"].get(str(number))
        if entry is None:
            raise ForgeError(f"#{number}: no such pull request in the stand-in")
        return {k: entry[k] for k in ("number", "title", "author", "state", "head")}

    def commits(self, number):
        return list(self.data["pulls"][str(number)]["commits"])

    def association(self, login):
        return self.data.get("associations", {}).get(login, "NONE")

    def react(self, comment_id, content):
        self.data.setdefault("reactions", []).append({"comment": comment_id, "content": content})
        self.save()
        self.record("react", "POST", f"/repos/{self.repository}/issues/comments/{comment_id}/reactions", extra={"content": content})

    def create_comment(self, number, body):
        comment_id = self.data.setdefault("next_comment", 900001)
        self.data["next_comment"] = comment_id + 1
        self.data.setdefault("comments", {})[str(comment_id)] = {"pr": number, "body": body, "user": "title-runs[bot]"}
        self.save()
        self.record("new", "POST", f"/repos/{self.repository}/issues/{number}/comments", body, {"comment_id": comment_id})
        return comment_id

    def edit_comment(self, comment_id, body):
        comment = self.data.get("comments", {}).get(str(comment_id))
        if comment is None:
            raise ForgeError(f"comment {comment_id} does not exist")
        comment["body"] = body
        self.save()
        self.record("edit", "PATCH", f"/repos/{self.repository}/issues/comments/{comment_id}", body, {"comment_id": comment_id})
