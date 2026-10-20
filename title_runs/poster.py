"""Post or edit the bot's comment. Dry-run by default: the body and the API call it would make go to the outbox.

The real poster is used only when poster.enabled is true in the config and is not asked for a dry run. It reads the
bot's token from the environment variable poster.token_env (a fine-grained token of the bot account, see README), edits
the bot's existing comment by id, and posts a new one only when the report's rule says so.
"""

import datetime
import json
from pathlib import Path

from .github import Rest


def outbox_dir(state_dir, number):
    return Path(state_dir) / "outbox" / str(number)


def post(config, state, number, body, action, reason, dry_run=True):
    entry = state.pr(number)
    comment_id = entry.get("comment_id")
    if action == "edit" and comment_id:
        method, path = "PATCH", f"/repos/{config.repo}/issues/comments/{comment_id}"
    else:
        action, method, path = "new", "POST", f"/repos/{config.repo}/issues/{number}/comments"
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    record = {"action": action, "reason": reason, "method": method, "path": path, "comment_id": comment_id if action == "edit" else None,
              "head": (state.current(number) or {}).get("head"), "at": stamp}
    if dry_run or not config.poster_enabled:
        directory = outbox_dir(config.state_dir, number)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / f"{stamp}-{action}.md").write_text(body)
        record["body_file"] = str(directory / f"{stamp}-{action}.md")
        record["dry_run"] = True
        (directory / f"{stamp}-{action}.json").write_text(json.dumps({**record, "request": {"method": method, "path": path, "json": {"body": "<body_file>"}}}, indent=2))
        if action == "new":
            entry["comment_id"] = entry.get("comment_id") or f"dry-run-{number}"
    else:
        reply = Rest(config.poster_token_env).call(method, path, {"body": body})
        entry["comment_id"] = reply["id"]
        record["url"] = reply.get("html_url")
        record["dry_run"] = False
    entry.setdefault("comment_posts", []).append(record)
    return record
