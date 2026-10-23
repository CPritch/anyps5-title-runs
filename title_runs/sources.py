"""Source trees for a job: main, and a PR's head merged onto that main locally.

A job fetches exactly the head's SHA and main and merges them here; it never builds refs/pull/N/merge or whatever the
branch points at later. The merge is made with a fixed identity and the head commit's own date, so the same main and
head give the same merge commit on every machine.

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


def fetch_head(repo_dir, remote, head, main_branch="main"):
    """Fetch the head commit by its SHA (GitHub serves any commit reachable from a ref, refs/pull/* included) and
    main's current tip. Returns main's SHA."""
    git(repo_dir, "fetch", "--no-tags", "-q", remote, f"+refs/heads/{main_branch}:refs/title-runs/main")
    if subprocess.run(["git", "-C", str(repo_dir), "cat-file", "-e", f"{head}^{{commit}}"], capture_output=True).returncode != 0:
        git(repo_dir, "fetch", "--no-tags", "-q", remote, head)
    if git(repo_dir, "rev-parse", f"{head}^{{commit}}") != head:
        raise SourceError(f"{head} did not resolve to itself")
    git(repo_dir, "update-ref", f"refs/title-runs/approved/{head}", head)
    return git(repo_dir, "rev-parse", "refs/title-runs/main")


def fetch_pinned(repo_dir, remote, head, main):
    """fetch_head for a main fixed in advance (local tests pin main for a while): the head and that
    main, both by SHA. Returns main."""
    for sha in (main, head):
        if subprocess.run(["git", "-C", str(repo_dir), "cat-file", "-e", f"{sha}^{{commit}}"], capture_output=True).returncode != 0:
            git(repo_dir, "fetch", "--no-tags", "-q", remote, sha)
        if git(repo_dir, "rev-parse", f"{sha}^{{commit}}") != sha:
            raise SourceError(f"{sha} did not resolve to itself")
    git(repo_dir, "update-ref", f"refs/title-runs/approved/{head}", head)
    return main


def main_tip(remote, main_branch="main"):
    """The SHA main is at on remote now, without fetching anything."""
    out = subprocess.run(["git", "ls-remote", remote, f"refs/heads/{main_branch}"], capture_output=True, text=True, timeout=120)
    if out.returncode != 0 or not out.stdout.strip():
        raise SourceError(f"could not read main from {remote}: {out.stderr.strip()[:200]}")
    return out.stdout.split()[0]


def pull_heads(remote):
    """{number: head SHA} for every pull request of remote (refs/pull/N/head), from git in one call: GitHub doesn't
    count git against its API's limit."""
    out = subprocess.run(["git", "ls-remote", remote, "refs/pull/*/head"], capture_output=True, text=True, timeout=120)
    if out.returncode != 0:
        raise SourceError(f"could not read the pull requests' heads from {remote}: {out.stderr.strip()[:200]}")
    heads = {}
    for line in out.stdout.splitlines():
        sha, _, ref = line.partition("\t")
        number = ref.removeprefix("refs/pull/").removesuffix("/head")
        if number.isdigit():
            heads[int(number)] = sha
    return heads


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


def carry(repo_dir, remote, main, fixes):
    """main with fixes merged onto it, for both sides of local tests (a main that doesn't run the game without them).
    fixes: [(PR number, head SHA)], merged in order without a worktree, each with the fixed identity and its head's date,
    so the same main and heads give the same base everywhere. A fix whose head main already has is left out.
    Returns (base, [{"pr", "head"}] carried, [PR numbers main already has]); raises SourceError on a conflict."""
    if not fixes:
        return main, [], []
    for sha in [main] + [head for _, head in fixes]:
        if subprocess.run(["git", "-C", str(repo_dir), "cat-file", "-e", f"{sha}^{{commit}}"], capture_output=True).returncode != 0:
            git(repo_dir, "fetch", "--no-tags", "-q", remote, sha)
    base, carried, in_main = main, [], []
    for number, head in fixes:
        if subprocess.run(["git", "-C", str(repo_dir), "merge-base", "--is-ancestor", head, main], capture_output=True).returncode == 0:
            in_main.append(number)
            continue
        merged = subprocess.run(["git", "-C", str(repo_dir), "merge-tree", "--write-tree", base, head], capture_output=True, text=True)
        if merged.returncode != 0:
            raise SourceError(f"#{number} ({head[:9]}) does not merge onto main {main[:9]}")
        date = git(repo_dir, "show", "-s", "--format=%cI", head)
        env = {**os.environ, **MERGE_IDENTITY, "GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date}
        base = subprocess.run(["git", "-C", str(repo_dir), "commit-tree", merged.stdout.split()[0], "-p", base, "-p", head,
                               "-m", f"Merge #{number} ({head[:12]}) onto main {main[:12]} for both sides (title runs)"],
                              capture_output=True, text=True, env=env, check=True).stdout.strip()
        carried.append({"pr": number, "head": head})
    if carried:
        git(repo_dir, "update-ref", f"refs/title-runs/base/{base}", base)  # kept from git's clean-up while it is a base
    return base, carried, in_main


def worktree(repo_dir, path, commit):
    path = Path(path)
    if (path / ".git").exists():
        git(path, "checkout", "-q", "--detach", "--force", commit)
        git(path, "clean", "-q", "-fdx", "-e", "/3rdparty/")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        git(repo_dir, "worktree", "add", "-q", "--detach", str(path), commit)
    return path


def _urls(tree):
    """{submodule path: url} from a tree's .gitmodules."""
    names = {}
    for kind in ("path", "url"):
        text = git(tree, "config", "-f", ".gitmodules", "--get-regexp", rf"submodule\..*\.{kind}", check=False)
        for line in text.splitlines():
            key, value = line.split(None, 1)
            names.setdefault(key[len("submodule."):-len(kind) - 1], {})[kind] = value
    return {n["path"]: n.get("url", "") for n in names.values() if "path" in n}


def _resolve(url, remote):
    """A .gitmodules url, with a relative one (../vgmstream.git) taken against the superproject's remote."""
    if url.startswith(("./", "../")) and remote:
        import posixpath
        import urllib.parse
        parts = urllib.parse.urlsplit(remote.rstrip("/"))
        return urllib.parse.urlunsplit(parts._replace(path=posixpath.normpath(posixpath.join(parts.path, url))))
    return url


def _source(source, url, cache):
    """The repository to take a submodule from: the clone's own checkout of it, or, for a submodule the clone doesn't
    have (upstream added it after the clone was made), a bare copy kept in cache, cloned from its url."""
    if Path(source).exists() and subprocess.run(["git", "-C", str(source), "rev-parse", "--git-dir"], capture_output=True).returncode == 0:
        return Path(source)
    if not url or cache is None:
        raise SourceError(f"{source}: the clone has no such submodule and its url is unknown")
    import hashlib
    bare = Path(cache) / (Path(url).stem + "-" + hashlib.sha256(url.encode()).hexdigest()[:10] + ".git")
    if not bare.exists():
        bare.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", "-q", "--bare", "--filter=blob:none", url, str(bare)], capture_output=True, check=False)
        if not bare.exists():
            raise SourceError(f"could not clone the submodule {url}")
    return bare


def _fill(source, target, pin, url="", cache=None, remote=None):
    """Extract <pin> of the repository at <source> into <target>, then its own submodules, recursively."""
    source = _source(source, url, cache)
    if subprocess.run(["git", "-C", str(source), "cat-file", "-e", f"{pin}^{{commit}}"], capture_output=True).returncode != 0:
        git(source, "fetch", "-q", "origin", pin)  # a bare copy's origin is its url
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    archive = git(source, "archive", "--format=tar", pin, binary=True)
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        tar.extractall(target, filter="tar")
    if (target / ".gitmodules").exists():
        urls = _urls(target)
        for sub, nested in _pins(source, target, pin).items():
            _fill(Path(source) / sub, target / sub, nested, _resolve(urls.get(sub, ""), url or remote), cache, url or remote)


def _pins(repo, tree, commit):
    text = git(tree, "config", "-f", ".gitmodules", "--get-regexp", r"submodule\..*\.path", check=False)
    pins = {}
    for line in text.splitlines():
        sub = line.split(None, 1)[1]
        entry = git(repo, "ls-tree", commit, sub).split()
        if len(entry) >= 3 and entry[1] == "commit":
            pins[sub] = entry[2]
    return pins


def submodules(repo_dir, path, commit, remote=None):
    """Fill each submodule directory of the worktree with the tree its pin names, nested submodules included (the
    clone's own nested checkouts supply them). Returns {path: pin}. The pins a worktree holds are recorded next to it
    (<worktree>.pins.json), not inside it, so the tree stays clean."""
    path = Path(path)
    record = path.with_name(path.name + ".pins.json")
    held = json.loads(record.read_text()) if record.exists() else {}
    pins = _pins(repo_dir, path, commit)
    urls = _urls(path)
    cache = Path(git(repo_dir, "rev-parse", "--path-format=absolute", "--git-common-dir")) / "title-runs-modules"
    for sub, pin in pins.items():
        target = path / sub
        if held.get(sub) == pin and target.is_dir() and any(target.iterdir()):
            continue
        _fill(Path(repo_dir) / sub, target, pin, _resolve(urls.get(sub, ""), remote), cache, remote)
        held[sub] = pin
        record.write_text(json.dumps(held, indent=1, sort_keys=True))
    return pins
