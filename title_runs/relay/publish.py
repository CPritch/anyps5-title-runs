"""The publish workflow: a push to the results repository -> checked results -> the App's comment.

A push by a tester (config.json's testers) to the main branch may only add, change or remove
claims/<job>/<machine>.json and add or change results/<job>/<machine>.json for that tester's machines; a push that touches anything else is refused whole, and none
of its results is posted. The queue, the configuration and the comment state are read from the state branch, which
testers cannot push to (the repository's rules protect it), never from what the push brought. Each result is checked (formats.check_result) and against
- its claim: the same tester, machine and head, and pushed before the claim expired;
- the queue: a result marked "queue" must be for the PR's approved head, or for an approved head it has moved on
  from (earlier); one marked "tester" must be for a commit of the PR, and is shown apart, as run on the tester's trust.
Accepted results are listed in comments.json with the SHA-256 of their content; the comment shows only those.
"""

import json
import re
import subprocess
from pathlib import Path

from . import comment
from .. import formats

CLAIM = re.compile(r"claims/(\d+-[0-9a-f]{12})/([a-z0-9][a-z0-9-]{0,31})\.json")
RESULT = re.compile(r"results/(\d+-[0-9a-f]{12})/([a-z0-9][a-z0-9-]{0,31})\.json")


def changed_paths(checkout, before, after):
    """(status, path) of the files the push changed (git diff --name-status before..after)."""
    if not before or set(before) == {"0"}:
        args = ["show", "--name-status", "--pretty=format:", after]
    else:
        args = ["diff", "--name-status", f"{before}..{after}"]
    out = subprocess.run(["git", "-C", str(checkout), *args], capture_output=True, text=True, check=True).stdout
    return [(line.split("\t")[0][0], line.split("\t")[-1]) for line in out.splitlines() if line.strip()]


class Refused(Exception):
    pass


def check_result(checkout, queue, forge, actor, path, at):
    data = json.loads((Path(checkout) / path).read_text())
    formats.check_result(data, path)
    claim_file = Path(checkout) / formats.claim_path(data["job"], data["machine"])
    if not claim_file.exists():
        raise Refused(f"{path}: no claim {formats.claim_path(data['job'], data['machine'])}")
    claim = formats.check_claim(json.loads(claim_file.read_text()), formats.claim_path(data["job"], data["machine"]))
    if claim["tester"] != actor or data["tester"] != actor:
        raise Refused(f"{path}: claimed by {claim['tester']}, result by {data['tester']}, pushed by {actor}")
    if claim["head"] != data["head"]:
        raise Refused(f"{path}: the claim is for {claim['head'][:9]}, the result for {data['head'][:9]}")
    if formats.claim_expired(claim, at):
        raise Refused(f"{path}: pushed after its claim expired ({claim['expires']})")
    if data["trust"] == "queue":
        entry = next((e for e in queue["entries"] if e["pr"] == data["pr"]), None)
        approved = ([entry["head"]] + entry["earlier"]) if entry else []
        if data["head"] not in approved:
            raise Refused(f"{path}: {data['head'][:9]} is not a head a maintainer approved for #{data['pr']}")
    elif data["head"] not in forge.commits(data["pr"]):
        raise Refused(f"{path}: {data['head'][:9]} is not a commit of #{data['pr']}")
    return data


def publish(state, data, forge, actor, before, after, at=None, log=print):
    """state: a checkout of the state branch (config, queue, comments; the workflows write it); data: a checkout of
    main at the pushed commit (claims and results). Returns {"accepted": [paths], "refused": [(path, reason)],
    "posted": {pr: (action, reason)}} and writes comments.json in state."""
    state, checkout, at = Path(state), Path(data), at or formats.now()
    config = formats.check_config(json.loads((state / "config.json").read_text()))
    queue = formats.check_queue(json.loads((state / "queue.json").read_text()))
    comments_file = state / "comments.json"
    comments = json.loads(comments_file.read_text()) if comments_file.exists() else formats.empty_comments()
    comments.setdefault("accepted", {})
    report = {"accepted": [], "refused": [], "posted": {}}
    paths = changed_paths(checkout, before, after)
    if actor not in config["testers"]:
        results = [p for _, p in paths if p.startswith("results/")]
        report["refused"] = [(p, f"{actor} is not a tester in config.json") for p in results]
        for p, reason in report["refused"]:
            log(f"refused {p}: {reason}")
        return report
    machines = config["testers"][actor].get("machines", [])
    for status, path in paths:
        found = CLAIM.fullmatch(path) or RESULT.fullmatch(path)
        allowed = ("A", "M", "D") if CLAIM.fullmatch(path) else ("A", "M")
        if found is None or found.group(2) not in machines or status not in allowed:
            report["refused"] = [(path, f"a push by {actor} may only add or change claims and results of {', '.join(machines)}; "
                                        f"it {'deleted' if status == 'D' else 'changed'} {path}")]
            log(f"refused the whole push: {report['refused'][0][1]}")
            return report
    prs = set()
    for _, path in paths:
        if not RESULT.fullmatch(path):
            continue
        try:
            data = check_result(checkout, queue, forge, actor, path, at)
        except (Refused, formats.FormatError, json.JSONDecodeError) as error:
            report["refused"].append((path, str(error)))
            comments["accepted"].pop(path, None)
            log(f"refused {path}: {error}")
            continue
        comments["accepted"][path] = {"pr": data["pr"], "sha256": comment.digest((checkout / path).read_bytes()), "at": formats.iso(at), "by": actor}
        report["accepted"].append(path)
        prs.add(data["pr"])
        log(f"accepted {path}")
    for pr in sorted(prs):
        posted = comment.refresh(checkout, forge, queue, comments, pr, at)
        if posted:
            report["posted"][pr] = posted
            log(f"#{pr}: {posted[0]} comment ({posted[1]})")
    comments_file.write_text(json.dumps(comments, indent=2) + "\n")
    return report
