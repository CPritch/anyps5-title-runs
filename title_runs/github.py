"""GitHub access: GraphQL for reading (no search API), REST for the bot's comment.

Reads go through either the gh CLI's login (client "gh") or a token in an environment variable (client "token").
Every GraphQL query asks for rateLimit, and a query is refused once the remaining budget is below the configured
reserve, so a poller never spends what other tools on the same account need.
"""

import json
import os
import subprocess
import urllib.request

API = "https://api.github.com"


class BudgetExhausted(RuntimeError):
    pass


class GraphQL:
    def __init__(self, client="gh", token_env="TITLE_RUNS_GITHUB_TOKEN", reserve=500):
        self.client, self.token_env, self.reserve = client, token_env, reserve
        self.remaining = None
        self.reset_at = None
        self.spent = 0

    def _post(self, payload):
        if self.client == "gh":
            result = subprocess.run(["gh", "api", "graphql", "--input", "-"], input=json.dumps(payload), capture_output=True, text=True)
            if result.returncode != 0:
                raise RuntimeError(f"gh api graphql failed: {result.stderr.strip()[:500]}")
            return json.loads(result.stdout)
        token = os.environ.get(self.token_env)
        if not token:
            raise RuntimeError(f"no token in ${self.token_env}")
        request = urllib.request.Request(f"{API}/graphql", data=json.dumps(payload).encode(), method="POST",
                                         headers={"Authorization": f"bearer {token}", "Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read())

    def query(self, query, variables=None):
        if self.remaining is not None and self.remaining < self.reserve:
            raise BudgetExhausted(f"GraphQL budget {self.remaining} is below the reserve {self.reserve} (resets {self.reset_at})")
        reply = self._post({"query": query, "variables": variables or {}})
        if reply.get("errors"):
            raise RuntimeError(f"GraphQL errors: {json.dumps(reply['errors'])[:500]}")
        data = reply["data"]
        limit = data.get("rateLimit") or {}
        if limit:
            self.remaining, self.reset_at = limit.get("remaining"), limit.get("resetAt")
            self.spent += limit.get("cost", 0)
        return data


class Rest:
    """The bot's REST calls (comments). Only used by the real poster."""

    def __init__(self, token_env):
        self.token_env = token_env

    def call(self, method, path, body=None):
        token = os.environ.get(self.token_env)
        if not token:
            raise RuntimeError(f"no token in ${self.token_env}")
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(f"{API}{path}", data=data, method=method,
                                         headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                                                  "X-GitHub-Api-Version": "2022-11-28", "Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read() or b"null")
