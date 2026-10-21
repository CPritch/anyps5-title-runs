"""title-runs export-results-repo DIR [OWNER/ANYPS5 OWNER/RESULTS]: fill a results repository from results_repo/ (the
relay workflow, config.json, README.md). An existing config.json is kept. No code goes into the results repository:
the workflow checks out the tool at the commit config.json pins."""

import json
import shutil
import subprocess
from pathlib import Path

from . import ROOT, formats

TEMPLATE = ROOT / "results_repo"


def export(dest, repository=None, results_repository=None, maintainers=None, app=None, tool=None):
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copytree(TEMPLATE / ".github", dest / ".github", dirs_exist_ok=True)
    if not (dest / "README.md").exists():
        shutil.copy2(TEMPLATE / "README.md", dest / "README.md")
    config = json.loads((dest / "config.json").read_text()) if (dest / "config.json").exists() else json.loads((TEMPLATE / "config.json").read_text())
    for key, value in (("repository", repository), ("results_repository", results_repository), ("maintainers", maintainers), ("app", app), ("tool", tool)):
        if value is not None:
            config[key] = value
    formats.check_config(config)
    (dest / "config.json").write_text(json.dumps(config, indent=2) + "\n")
    return dest


def head_commit():
    """This checkout's HEAD, which the workflow will check out: it must be on the tool's remote already."""
    head = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    remote = subprocess.run(["git", "-C", str(ROOT), "branch", "-r", "--contains", head], capture_output=True, text=True).stdout.strip()
    if not remote:
        raise SystemExit(f"{head[:9]} is not pushed: the workflow checks out the tool at this commit from its repository")
    return head


def commit(dest):
    """dest as a git repository on main with one commit of everything in it."""
    dest = Path(dest)
    if not (dest / ".git").exists():
        subprocess.run(["git", "init", "-q", "-b", "main", str(dest)], check=True)
    subprocess.run(["git", "-C", str(dest), "add", "-A"], check=True)
    if subprocess.run(["git", "-C", str(dest), "diff", "--cached", "--quiet"]).returncode != 0:
        subprocess.run(["git", "-C", str(dest), "commit", "-q", "-m", "The results repository: config.json, the relay workflow, README"], check=True)
