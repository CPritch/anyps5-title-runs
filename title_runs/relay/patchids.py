"""Patch-ids of a PR head's own commits: whether a push changed anything a maintainer looked at.

A head's own commits are those after its merge base with main (merges left out). Two heads carry the same code when
their own commits have the same stable patch-ids in the same order: a rebase onto a newer main, or a force-push of the
same commits, changes the SHAs but not the patch-ids. The workflow fetches AnyPS5's history into a git directory
(blob-less; git fetches the blobs a patch needs), the stand-in uses a local clone.
"""

import subprocess


class PatchIdError(RuntimeError):
    pass


def git(git_dir, *args, stdin=None):
    result = subprocess.run(["git", "--git-dir", str(git_dir), *args], input=stdin, capture_output=True)
    if result.returncode != 0:
        raise PatchIdError(f"git {' '.join(args)}: {result.stderr.decode(errors='replace').strip()[:300]}")
    return result.stdout


def ensure(git_dir, shas, remote=None):
    """Fetch the commits that are not in git_dir yet from remote (by SHA; GitHub serves commits reachable from a ref)."""
    missing = [sha for sha in shas if subprocess.run(["git", "--git-dir", str(git_dir), "cat-file", "-e", f"{sha}^{{commit}}"],
                                                     capture_output=True).returncode != 0]
    if missing and remote:
        git(git_dir, "fetch", "--quiet", "--no-tags", remote, *missing)


def own_patch_ids(git_dir, head, main):
    base = git(git_dir, "merge-base", main, head).decode().strip()
    log = git(git_dir, "log", "--reverse", "--no-merges", "-p", "--no-color", "--pretty=format:commit %H", f"{base}..{head}")
    if not log.strip():
        return []
    ids = git(git_dir, "patch-id", "--stable", stdin=log).decode().split("\n")
    return [line.split()[0] for line in ids if line.strip()]


def same_code(git_dir, approved, new, main):
    """(True, reason) when new's own commits have approved's patch-ids in order."""
    a, b = own_patch_ids(git_dir, approved, main), own_patch_ids(git_dir, new, main)
    if a and a == b:
        return True, f"a rebase with the same {len(a)} patch-id(s) as {approved[:9]}"
    return False, f"{len(b)} own commit(s) whose patch-ids differ from {approved[:9]}'s {len(a)}"
