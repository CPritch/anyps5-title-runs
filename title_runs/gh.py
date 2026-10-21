"""Everything that talks to GitHub, behind one interface: Repo, one repository seen by one identity (the App on AnyPS5,
the workflow on the results repository, a tester or a maintainer signed in through the App).

GitHubRepo calls the REST API with a token. FakeGitHub keeps a stand-in for both repositories (pull requests, issues,
comments, labels, events, workflow runs, accounts) and the device flow in one JSON file, and writes every write it is
asked to make to an outbox, with the identity that made it: the stand-in until the App and the repository exist.
"""

import datetime
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://api.github.com"
WRITE = ("admin", "maintain", "write")


class GitHubError(RuntimeError):
    pass


def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class Repo:
    """One repository as one identity. Lists are oldest first."""

    repository = ""

    def login(self): raise NotImplementedError                      # the acting account (None for the App or the workflow)
    def pull(self, number): raise NotImplementedError               # {"number", "title", "author", "state", "head", "head_ref", "labels"}
    def commits(self, number): raise NotImplementedError            # the PR's commit SHAs
    def permission(self, login): raise NotImplementedError          # admin, maintain, write, triage, read or none
    def issue_events(self, after=0): raise NotImplementedError      # repository-wide: [{"id", "event", "label", "actor", "created_at", "issue"}]
    def comments(self, since=None, issue=None): raise NotImplementedError  # [{"id", "issue", "body", "user", "association", "created_at"}]
    def issues(self, label=None, state="open"): raise NotImplementedError  # [{"number", "title", "body", "user", "labels", "state", "created_at"}]
    def workflow_runs(self, head_sha=None, branch=None): raise NotImplementedError  # [{"created_at", "actor", "event", "head_sha"}]
    def label_actor(self, number, label): raise NotImplementedError  # who last added label to the issue, or None
    def create_issue(self, title, body, labels=()): raise NotImplementedError
    def edit_issue(self, number, body=None, state=None): raise NotImplementedError
    def add_labels(self, number, labels): raise NotImplementedError
    def remove_label(self, number, name): raise NotImplementedError
    def create_comment(self, number, body): raise NotImplementedError
    def edit_comment(self, comment_id, body): raise NotImplementedError
    def delete_comment(self, comment_id): raise NotImplementedError
    def react(self, comment_id, content): raise NotImplementedError


class GitHubRepo(Repo):
    def __init__(self, repository, token=None, token_env=None):
        self.repository = repository
        self.token = token or (os.environ.get(token_env) if token_env else None)
        self._login = None

    def call(self, method, path, body=None, params=None):
        url = f"{API}{path}" + (f"?{urllib.parse.urlencode(params)}" if params else "")
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28", "Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        request = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None, method=method, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return json.loads(response.read() or b"null")
        except urllib.error.HTTPError as error:
            raise GitHubError(f"{method} {path}: HTTP {error.code} {error.read()[:300]!r}") from error

    def pages(self, path, params=None, limit=10):
        out = []
        for page in range(1, limit + 1):
            batch = self.call("GET", path, params={**(params or {}), "per_page": 100, "page": page})
            items = batch.get("workflow_runs", []) if isinstance(batch, dict) else batch
            out += items
            if len(items) < 100:
                break
        return out

    def login(self):
        if self._login is None and self.token:
            self._login = self.call("GET", "/user")["login"]
        return self._login

    def pull(self, number):
        data = self.call("GET", f"/repos/{self.repository}/pulls/{number}")
        return {"number": number, "title": data["title"], "author": data["user"]["login"], "head": data["head"]["sha"],
                "head_ref": data["head"]["ref"], "state": "merged" if data.get("merged_at") else data["state"],
                "labels": [label["name"] for label in data.get("labels", [])]}

    def commits(self, number):
        return [c["sha"] for c in self.pages(f"/repos/{self.repository}/pulls/{number}/commits", limit=3)]

    def permission(self, login):
        try:
            return self.call("GET", f"/repos/{self.repository}/collaborators/{login}/permission").get("permission", "none")
        except GitHubError:
            return "none"

    def issue_events(self, after=0):
        events = []
        for page in range(1, 11):  # newest first; stop at the cursor
            batch = self.call("GET", f"/repos/{self.repository}/issues/events", params={"per_page": 100, "page": page})
            fresh = [e for e in batch if e["id"] > after]
            events += fresh
            if len(fresh) < len(batch) or len(batch) < 100:
                break
        return sorted(({"id": e["id"], "event": e["event"], "label": (e.get("label") or {}).get("name"), "actor": (e.get("actor") or {}).get("login"),
                        "created_at": e["created_at"], "issue": (e.get("issue") or {}).get("number")} for e in events), key=lambda e: e["id"])

    def comments(self, since=None, issue=None):
        """Comments created at or after since, oldest first. GitHub's own since= means updated since, which brings back
        every old comment edited later (bots edit theirs all the time), so the repository's comments are listed newest
        first by creation and read back only to since."""
        def shape(c):
            return {"id": c["id"], "issue": int(c["issue_url"].rsplit("/", 1)[1]), "body": c["body"], "user": c["user"]["login"],
                    "association": c.get("author_association", "NONE"), "created_at": c["created_at"]}
        if issue:
            out = [shape(c) for c in self.pages(f"/repos/{self.repository}/issues/{issue}/comments")]
        else:
            out = []
            for page in range(1, 11):
                batch = self.call("GET", f"/repos/{self.repository}/issues/comments",
                                  params={"sort": "created", "direction": "desc", "per_page": 100, "page": page})
                fresh = [shape(c) for c in batch if since is None or c["created_at"] >= since]
                out += fresh
                if len(fresh) < len(batch) or len(batch) < 100:
                    break
        out = [c for c in out if since is None or c["created_at"] >= since]
        return sorted(out, key=lambda c: (c["created_at"], c["id"]))

    def issues(self, label=None, state="open"):
        params = {"state": state, **({"labels": label} if label else {})}
        return [{"number": i["number"], "title": i["title"], "body": i.get("body") or "", "user": i["user"]["login"],
                 "labels": [label["name"] for label in i.get("labels", [])], "state": i["state"], "created_at": i["created_at"]}
                for i in self.pages(f"/repos/{self.repository}/issues", params) if "pull_request" not in i]

    def workflow_runs(self, head_sha=None, branch=None):
        params = {k: v for k, v in (("head_sha", head_sha), ("branch", branch)) if v}
        runs = self.pages(f"/repos/{self.repository}/actions/runs", params, limit=2)
        return sorted(({"created_at": r["created_at"], "actor": (r.get("actor") or {}).get("login"), "event": r["event"], "head_sha": r["head_sha"]}
                       for r in runs), key=lambda r: r["created_at"])

    def label_actor(self, number, label):
        events = self.pages(f"/repos/{self.repository}/issues/{number}/events", limit=3)
        added = [e for e in events if e["event"] == "labeled" and (e.get("label") or {}).get("name") == label]
        return (added[-1].get("actor") or {}).get("login") if added else None

    def create_issue(self, title, body, labels=()):
        return self.call("POST", f"/repos/{self.repository}/issues", {"title": title, "body": body, "labels": list(labels)})["number"]

    def edit_issue(self, number, body=None, state=None):
        self.call("PATCH", f"/repos/{self.repository}/issues/{number}", {k: v for k, v in (("body", body), ("state", state)) if v is not None})

    def add_labels(self, number, labels):
        self.call("POST", f"/repos/{self.repository}/issues/{number}/labels", {"labels": list(labels)})

    def remove_label(self, number, name):
        try:
            self.call("DELETE", f"/repos/{self.repository}/issues/{number}/labels/{urllib.parse.quote(name)}")
        except GitHubError:
            pass

    def create_comment(self, number, body):
        return self.call("POST", f"/repos/{self.repository}/issues/{number}/comments", {"body": body})["id"]

    def edit_comment(self, comment_id, body):
        self.call("PATCH", f"/repos/{self.repository}/issues/comments/{comment_id}", {"body": body})

    def delete_comment(self, comment_id):
        self.call("DELETE", f"/repos/{self.repository}/issues/comments/{comment_id}")

    def react(self, comment_id, content):
        self.call("POST", f"/repos/{self.repository}/issues/comments/{comment_id}/reactions", {"content": content})


class FakeGitHub:
    """The stand-in's GitHub: {"repos": {name: {"pulls": {n: {...}}, "issues": {n: {...}}, "comments": {id: {...}},
    "events": [...], "runs": [...], "permissions": {login: permission}, "next": n}}, "next_id": n, "device": {...},
    "tokens": {token: login}}. Writes go to the outbox as <n>-<identity>-<action>.json (and .md for bodies)."""

    def __init__(self, path, outbox=None, clock=None):
        self.path, self.outbox = Path(path), Path(outbox) if outbox else None
        self.clock = clock or now_iso
        self.data = json.loads(self.path.read_text()) if self.path.exists() else {"repos": {}, "next_id": 1000}

    @classmethod
    def create(cls, path, outbox=None):
        fake = cls(path, outbox)
        fake.save()
        return fake

    def reload(self):
        self.data = json.loads(self.path.read_text())

    def save(self):
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.data, indent=1, sort_keys=True))
        os.replace(temporary, self.path)

    def repo(self, name):
        return self.data["repos"].setdefault(name, {"pulls": {}, "issues": {}, "comments": {}, "events": [], "runs": [], "permissions": {}, "next": 1})

    def next_id(self):
        self.data["next_id"] += 1
        return self.data["next_id"]

    def record(self, who, action, repository, request, body=None):
        if self.outbox is None:
            return
        self.outbox.mkdir(parents=True, exist_ok=True)
        number = len(list(self.outbox.glob("*.json"))) + 1
        name = f"{number:03d}-{who.replace('[', '').replace(']', '')}-{action}"
        (self.outbox / f"{name}.json").write_text(json.dumps({"as": who, "action": action, "repository": repository, **request}, indent=2))
        if body is not None:
            (self.outbox / f"{name}.md").write_text(body)

    @classmethod
    def standin(cls, path):
        """The stand-in's fake (standin.py's layout): github.json with the outbox beside it."""
        return cls(path, Path(path).parent / "outbox")

    def as_(self, repository, login=None, identity=None):
        """A FakeRepo acting as login (a user), or as identity (the App or the workflow) when login is None."""
        return FakeRepo(self, repository, login, identity or login or "anonymous")


class FakeRepo(Repo):
    def __init__(self, fake, repository, user, identity):
        self.fake, self.repository, self.user, self.identity = fake, repository, user, identity

    def r(self):
        self.fake.reload()
        return self.fake.repo(self.repository)

    def login(self):
        return self.user

    def pull(self, number):
        pull = self.r()["pulls"].get(str(number))
        if pull is None:
            raise GitHubError(f"#{number}: no such pull request in the stand-in")
        return {k: pull.get(k) for k in ("number", "title", "author", "state", "head", "head_ref")} | {"labels": list(pull.get("labels", []))}

    def commits(self, number):
        return list(self.r()["pulls"][str(number)]["commits"])

    def permission(self, login):
        return self.r()["permissions"].get(login, "none")

    def issue_events(self, after=0):
        return [e for e in self.r()["events"] if e["id"] > after]

    def comments(self, since=None, issue=None):
        out = [c for c in self.r()["comments"].values() if (issue is None or c["issue"] == issue) and (since is None or c["created_at"] >= since)]
        return sorted(out, key=lambda c: (c["created_at"], c["id"]))

    def issues(self, label=None, state="open"):
        out = [i for i in self.r()["issues"].values() if (state == "all" or i["state"] == state) and (label is None or label in i["labels"])]
        return sorted(out, key=lambda i: i["number"])

    def workflow_runs(self, head_sha=None, branch=None):
        return sorted((x for x in self.r()["runs"] if (head_sha is None or x["head_sha"] == head_sha) and (branch is None or x.get("branch") == branch)),
                      key=lambda x: x["created_at"])

    def label_actor(self, number, label):
        added = [e for e in self.r()["events"] if e["issue"] == number and e["event"] == "labeled" and e["label"] == label]
        return added[-1]["actor"] if added else None

    # -- writes ----------------------------------------------------------------------------------------------------------

    def _write(self, action, request, body=None):
        self.fake.save()
        self.fake.record(self.identity, action, self.repository, request, body)

    def _event(self, repo, event, number, label):
        repo["events"].append({"id": self.fake.next_id(), "event": event, "label": label, "actor": self.identity, "created_at": self.fake.clock(),
                               "issue": number})

    def create_issue(self, title, body, labels=()):
        repo = self.r()
        number = repo["next"]
        repo["next"] = number + 1
        repo["issues"][str(number)] = {"number": number, "title": title, "body": body, "user": self.identity, "labels": list(labels),
                                       "state": "open", "created_at": self.fake.clock()}
        for label in labels:
            self._event(repo, "labeled", number, label)
        self._write("create-issue", {"method": "POST", "path": f"/repos/{self.repository}/issues", "number": number, "title": title,
                                     "labels": list(labels)}, body)
        return number

    def _labels(self, repo, number):
        item = repo["issues"].get(str(number)) or repo["pulls"].get(str(number))
        if item is None:
            raise GitHubError(f"#{number}: no such issue or pull request")
        return item

    def edit_issue(self, number, body=None, state=None):
        repo = self.r()
        issue = repo["issues"][str(number)]
        if body is not None:
            issue["body"] = body
        if state is not None:
            issue["state"] = state
            self._event(repo, "closed" if state == "closed" else "reopened", number, None)
        self._write("edit-issue", {"method": "PATCH", "path": f"/repos/{self.repository}/issues/{number}", "state": state}, body)

    def add_labels(self, number, labels):
        repo = self.r()
        item = self._labels(repo, number)
        for label in labels:
            if label not in item.setdefault("labels", []):
                item["labels"].append(label)
                self._event(repo, "labeled", number, label)
        self._write("add-labels", {"method": "POST", "path": f"/repos/{self.repository}/issues/{number}/labels", "labels": list(labels)})

    def remove_label(self, number, name):
        repo = self.r()
        item = self._labels(repo, number)
        if name in item.get("labels", []):
            item["labels"].remove(name)
            self._event(repo, "unlabeled", number, name)
        self._write("remove-label", {"method": "DELETE", "path": f"/repos/{self.repository}/issues/{number}/labels/{name}"})

    def create_comment(self, number, body):
        repo = self.r()
        comment_id = self.fake.next_id()
        association = "OWNER" if repo["permissions"].get(self.identity) == "admin" else (
            "COLLABORATOR" if repo["permissions"].get(self.identity) in WRITE else "NONE")
        repo["comments"][str(comment_id)] = {"id": comment_id, "issue": number, "body": body, "user": self.identity, "association": association,
                                             "created_at": self.fake.clock()}
        self._write("comment", {"method": "POST", "path": f"/repos/{self.repository}/issues/{number}/comments", "comment_id": comment_id}, body)
        return comment_id

    def edit_comment(self, comment_id, body):
        repo = self.r()
        comment = repo["comments"].get(str(comment_id))
        if comment is None or comment["user"] != self.identity:
            raise GitHubError(f"comment {comment_id} is not {self.identity}'s")
        comment["body"] = body
        self._write("edit-comment", {"method": "PATCH", "path": f"/repos/{self.repository}/issues/comments/{comment_id}"}, body)

    def delete_comment(self, comment_id):
        repo = self.r()
        comment = repo["comments"].get(str(comment_id))
        if comment is None or comment["user"] != self.identity:
            raise GitHubError(f"comment {comment_id} is not {self.identity}'s")
        del repo["comments"][str(comment_id)]
        self._write("delete-comment", {"method": "DELETE", "path": f"/repos/{self.repository}/issues/comments/{comment_id}"})

    def react(self, comment_id, content):
        repo = self.r()
        repo["comments"][str(comment_id)].setdefault("reactions", []).append({"user": self.identity, "content": content})
        self._write("react", {"method": "POST", "path": f"/repos/{self.repository}/issues/comments/{comment_id}/reactions", "content": content})
