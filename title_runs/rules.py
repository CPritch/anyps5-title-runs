"""Which pull requests are followed, and whose pushes run without the tester's confirmation."""

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


def head_author(pr):
    nodes = (pr.get("commits") or {}).get("nodes") or []
    if not nodes:
        return None
    user = ((nodes[-1].get("commit") or {}).get("author") or {}).get("user")
    return user.get("login") if user else None


def followed(pr, config):
    """The reason a PR is followed, or None. Only open PRs are followed; drafts only when the config says so."""
    if pr.get("state") != "OPEN":
        return None
    if pr.get("isDraft") and not config.include_drafts:
        return None
    if pr["number"] in config.follow_prs:
        return "listed"
    if config.auto_unblocks:
        mine = sorted(unblocks(pr.get("body")) & set(config.titles))
        if mine:
            return "unblocks " + ", ".join(mine)
    chosen = sorted(labels(pr) & set(config.follow_labels))
    if chosen:
        return "label " + ", ".join(chosen)
    return None


def trusted(pr, config):
    """(True, reason) when this head may be built and run without asking the tester.

    The PR's author and the head commit's author (when GitHub links it to an account) must both be on the allowlist,
    or the PR carries one of the maintainer labels. Anything else waits for `title-runs confirm`."""
    marked = sorted(labels(pr) & set(config.maintainer_labels))
    if marked:
        return True, "maintainer label " + ", ".join(marked)
    author = (pr.get("author") or {}).get("login")
    committer = head_author(pr)
    if author not in config.authors:
        return False, f"author {author} is not on the allowlist"
    if committer is not None and committer not in config.authors:
        return False, f"head commit by {committer}, who is not on the allowlist"
    return True, f"author {author} is on the allowlist"
