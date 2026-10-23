"""What a pull request says about itself: the titles its template's Unblocks: line names, and its labels."""

import re

from .config import TITLE_ID

UNBLOCKS = re.compile(r"^\W*(?:\[[ xX]\]\s*)?Unblocks:\s*(.*)$", re.MULTILINE)


def unblocks(body):
    """Title IDs on the PR template's Unblocks: line(s), e.g. "- [x] Unblocks: PPSA01325 #3232"."""
    found = set()
    for line in UNBLOCKS.findall(body or ""):
        line = re.sub(r"<!--.*?-->", "", line)
        found.update(TITLE_ID.findall(line))
    return found


def labels(pr):
    return {label["name"] for label in (pr.get("labels") or {}).get("nodes", [])}

