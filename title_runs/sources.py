"""Source trees for a job: GitHub's merge of the PR (refs/pull/N/merge) and main at that merge's base.

Both sides are worktrees of the tester's clone (source.repo_dir), kept at fixed paths under the state directory so
their build directories stay valid and rebuild incrementally. Submodules are filled from the clone's own submodule
repositories at the commit each side pins (git archive), so a worktree never needs the network for them unless a pin
is missing locally, in which case that submodule repository fetches it.
"""

import io
import json
import shutil
import subprocess
import tarfile
from pathlib import Path


class SourceError(RuntimeError):
    pass


def git(directory, *args, check=True, binary=False):
    result = subprocess.run(["git", "-C", str(directory), *args], capture_output=True, text=not binary)
    if check and result.returncode != 0:
        raise SourceError(f"git {' '.join(args)} in {directory}: {(result.stderr or b'').strip() if binary else result.stderr.strip()}")
    return result.stdout if binary else result.stdout.strip()


def fetch_pr(repo_dir, remote, number):
    """Fetch the PR's head and GitHub's merge ref. Returns (head, merge, base) or raises when GitHub has no merge ref
    (the PR does not merge cleanly into its base branch)."""
    head_ref, merge_ref = f"refs/title-runs/pr-{number}/head", f"refs/title-runs/pr-{number}/merge"
    git(repo_dir, "fetch", "--no-tags", "-q", remote, f"+refs/pull/{number}/head:{head_ref}")
    merged = subprocess.run(["git", "-C", str(repo_dir), "fetch", "--no-tags", "-q", remote, f"+refs/pull/{number}/merge:{merge_ref}"], capture_output=True, text=True)
    head = git(repo_dir, "rev-parse", head_ref)
    if merged.returncode != 0:
        raise SourceError(f"#{number} has no merge ref (it does not merge cleanly into its base): {merged.stderr.strip()[:300]}")
    merge = git(repo_dir, "rev-parse", merge_ref)
    parents = git(repo_dir, "rev-list", "--parents", "-n", "1", merge).split()[1:]
    if len(parents) != 2:
        raise SourceError(f"#{number}: {merge} is not a merge commit")
    base, merged_head = parents
    if merged_head != head:
        raise SourceError(f"#{number}: GitHub's merge ref {merge[:9]} merges {merged_head[:9]}, not the head {head[:9]} (it is being recomputed; try again)")
    return head, merge, base


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
