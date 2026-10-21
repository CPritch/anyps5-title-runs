"""The App's one comment per PR: collect the PR's accepted results (results/, which only the workflow writes), render,
post or edit (comments.json keeps the comment's id and what each post showed)."""

import hashlib
import json
from pathlib import Path

from . import render
from .. import formats


def digest(text):
    return hashlib.sha256(text.encode() if isinstance(text, str) else text).hexdigest()


def accepted_results(state, pr):
    """{head: {machine: result}} for results of heads a maintainer approved, and for results run on a tester's trust."""
    queued, tester = {}, {}
    for path in sorted(Path(state).glob("results/*/*.json")):
        result = json.loads(path.read_text())
        if result.get("pr") != pr:
            continue
        group = queued if result["trust"] == "queue" else tester
        group.setdefault(result["head"], {})[result["machine"]] = result
    return queued, tester


def refresh(state, anyps5, queue, comments, pr, at, label="title-test"):
    """Post or edit the App's comment on pr (anyps5: the App on AnyPS5). Returns (action, reason) or None when the text
    did not change."""
    entry = next((e for e in queue["entries"] if e["pr"] == pr), None)
    stopped = next((s["by"] for s in reversed(queue.get("stopped", [])) if s["pr"] == pr), None)
    expired = [x for x in queue.get("expired", []) if x["pr"] == pr]
    refused = [x for x in queue.get("refused", []) if x["pr"] == pr]
    queued, tester = accepted_results(state, pr)
    order = (entry["earlier"] + [entry["head"]]) if entry else sorted(queued)
    ordered = {head: queued[head] for head in order if head in queued}
    ordered.update({head: results for head, results in queued.items() if head not in ordered})
    body = render.render(pr, entry, ordered, tester, stopped, expired, refused, label)
    shot = render.snapshot(queued, tester)
    record = comments["prs"].setdefault(str(pr), {"comment_id": None, "posts": []})
    if record["posts"] and record["posts"][-1].get("body_sha256") == digest(body):
        return None
    previous = record["posts"][-1]["heads"] if record["comment_id"] and record["posts"] else None
    action, reason = render.decide(previous, shot, order)
    if action == "edit" and record["comment_id"]:
        anyps5.edit_comment(record["comment_id"], body)
    else:
        action = "new"
        record["comment_id"] = anyps5.create_comment(pr, body)
    record["posts"].append({"action": action, "at": formats.iso(at), "reason": reason, "heads": shot, "body_sha256": digest(body)})
    return action, reason
