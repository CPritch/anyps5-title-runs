"""The App's one comment per PR: collect the PR's accepted results, render, post or edit (comments.json).

Only results the publish workflow accepted are shown: comments.json lists each accepted result file with the SHA-256
of the content it accepted, so a file changed afterwards in the repository is left out until it is accepted again.
"""

import hashlib
import json
from pathlib import Path

from . import render
from .. import formats


def digest(text):
    return hashlib.sha256(text.encode() if isinstance(text, str) else text).hexdigest()


def accepted_results(checkout, comments, pr):
    """{head: {machine: result}} for queue-trust results and for tester-trust results of pr."""
    queued, tester = {}, {}
    for path, record in comments.get("accepted", {}).items():
        file = Path(checkout) / path
        if record.get("pr") != pr or not file.exists() or digest(file.read_bytes()) != record["sha256"]:
            continue
        result = json.loads(file.read_text())
        group = queued if result["trust"] == "queue" else tester
        group.setdefault(result["head"], {})[result["machine"]] = result
    return queued, tester


def refresh(checkout, forge, queue, comments, pr, at):
    entry = next((e for e in queue["entries"] if e["pr"] == pr), None)
    stopped = next((s["by"] for s in reversed(queue.get("stopped", [])) if s["pr"] == pr), None)
    queued, tester = accepted_results(checkout, comments, pr)
    order = (entry["earlier"] + [entry["head"]]) if entry else sorted(queued)
    body = render.render(pr, entry, queued, tester, stopped)
    shot = render.snapshot(queued, tester)
    state = comments["prs"].setdefault(str(pr), {"comment_id": None, "posts": []})
    if state["posts"] and state["posts"][-1].get("body_sha256") == digest(body):
        return None
    previous = state["posts"][-1]["heads"] if state["comment_id"] and state["posts"] else None
    action, reason = render.decide(previous, shot, order)
    if action == "edit" and state["comment_id"]:
        forge.edit_comment(state["comment_id"], body)
    else:
        action = "new"
        state["comment_id"] = forge.create_comment(pr, body)
    state["posts"].append({"action": action, "at": formats.iso(at), "reason": reason, "heads": shot, "body_sha256": digest(body)})
    return action, reason
