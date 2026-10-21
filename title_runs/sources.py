"""Source trees for a job: main, and the approved commit merged onto that main locally.

Approval names a commit (DESIGN.md), so a job fetches exactly that SHA and current main and merges them here; it never
builds refs/pull/N/merge or the branch's head. The merge is made with a fixed identity and the approved commit's own
date, so the same main and head give the same merge commit on every machine.

Both sides are worktrees of the tester's clone (source.repo_dir), kept at fixed paths under the state directory so
their build directories stay valid and rebuild incrementally. Submodules are filled from the clone's own submodule
repositories at the commit each side pins (git archive), so a worktree never needs the network for them unless a pin
is missing locally, in which case that submodule repository fetches it. All of this runs before the build, outside
the build sandbox, which has no network.
"""

import io
import json
import os
import shutil
import subprocess
import tarfile
from pathlib import Path

MERGE_IDENTITY = {"GIT_AUTHOR_NAME": "anyps5-title-runs", "GIT_AUTHOR_EMAIL": "title-runs@localhost",
                  "GIT_COMMITTER_NAME": "anyps5-title-runs", "GIT_COMMITTER_EMAIL": "title-runs@localhost"}


class SourceError(RuntimeError):
    pass


def git(directory, *args, check=True, binary=False):
    result = subprocess.run(["git", "-C", str(directory), *args], capture_output=True, text=not binary)
    if check and result.returncode != 0:
        raise SourceError(f"git {' '.join(args)} in {directory}: {(result.stderr or b'').strip() if binary else result.stderr.strip()}")
    return result.stdout if binary else result.stdout.strip()


def fetch_approved(repo_dir, remote, head, main_branch="main"):
    """Fetch the approved commit by its SHA (GitHub serves any commit reachable from a ref, refs/pull/* included) and
    main's current tip. Returns main's SHA."""
    git(repo_dir, "fetch", "--no-tags", "-q", remote, f"+refs/heads/{main_branch}:refs/title-runs/main")
    if subprocess.run(["git", "-C", str(repo_dir), "cat-file", "-e", f"{head}^{{commit}}"], capture_output=True).returncode != 0:
        git(repo_dir, "fetch", "--no-tags", "-q", remote, head)
    if git(repo_dir, "rev-parse", f"{head}^{{commit}}") != head:
        raise SourceError(f"{head} did not resolve to itself")
    git(repo_dir, "update-ref", f"refs/title-runs/approved/{head}", head)
    return git(repo_dir, "rev-parse", "refs/title-runs/main")


def merge_onto(tree, main, head):
    """Merge head onto main in the worktree (already checked out at main). Returns the merge commit; raises SourceError
    when they conflict."""
    date = git(tree, "show", "-s", "--format=%cI", head)
    env = {**os.environ, **MERGE_IDENTITY, "GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date}
    merged = subprocess.run(["git", "-C", str(tree), "merge", "--no-ff", "--no-edit", "-q", "-m", f"Merge {head[:12]} onto main {main[:12]} (title runs)", head],
                            capture_output=True, text=True, env=env)
    if merged.returncode != 0:
        conflicts = git(tree, "diff", "--name-only", "--diff-filter=U", check=False).split()
        subprocess.run(["git", "-C", str(tree), "merge", "--abort"], capture_output=True)
        raise SourceError(f"{head[:9]} does not merge onto main {main[:9]}: " + (f"conflicts in {', '.join(conflicts[:5])}" if conflicts else merged.stderr.strip()[:200]))
    merge = git(tree, "rev-parse", "HEAD")
    parents = git(tree, "rev-list", "--parents", "-n", "1", merge).split()[1:]
    if parents != [main, head]:
        raise SourceError(f"the merge {merge[:9]} has parents {parents}, not main {main[:9]} and {head[:9]}")
    return merge


def worktree(repo_dir, path, commit):
    path = Path(path)
    if (path / ".git").exists():
        git(path, "checkout", "-q", "--detach", "--force", commit)
        git(path, "clean", "-q", "-fdx", "-e", "/3rdparty/")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        git(repo_dir, "worktree", "add", "-q", "--detach", str(path), commit)
    return path


def _fill(source, target, pin):
    """Extract <pin> of the repository at <source> into <target>, then its own submodules, recursively."""
    if subprocess.run(["git", "-C", str(source), "cat-file", "-e", f"{pin}^{{commit}}"], capture_output=True).returncode != 0:
        git(source, "fetch", "-q", "origin", pin)
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    archive = git(source, "archive", "--format=tar", pin, binary=True)
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        tar.extractall(target, filter="tar")
    if (target / ".gitmodules").exists():
        for sub, nested in _pins(source, target, pin).items():
            _fill(Path(source) / sub, target / sub, nested)


def _pins(repo, tree, commit):
    text = git(tree, "config", "-f", ".gitmodules", "--get-regexp", r"submodule\..*\.path", check=False)
    pins = {}
    for line in text.splitlines():
        sub = line.split(None, 1)[1]
        entry = git(repo, "ls-tree", commit, sub).split()
        if len(entry) >= 3 and entry[1] == "commit":
            pins[sub] = entry[2]
    return pins


def submodules(repo_dir, path, commit):
    """Fill each submodule directory of the worktree with the tree its pin names, nested submodules included (the
    clone's own nested checkouts supply them). Returns {path: pin}. The pins a worktree holds are recorded next to it
    (<worktree>.pins.json), not inside it, so the tree stays clean."""
    path = Path(path)
    record = path.with_name(path.name + ".pins.json")
    held = json.loads(record.read_text()) if record.exists() else {}
    pins = _pins(repo_dir, path, commit)
    for sub, pin in pins.items():
        target = path / sub
        if held.get(sub) == pin and target.is_dir() and any(target.iterdir()):
            continue
        _fill(Path(repo_dir) / sub, target, pin)
        held[sub] = pin
        record.write_text(json.dumps(held, indent=1, sort_keys=True))
    return pins
