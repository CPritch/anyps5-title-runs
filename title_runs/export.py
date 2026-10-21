"""title-runs export-results-repo MAIN_DIR STATE_DIR: fill the two branches of a results repository from
results_repo/: main (the workflows, README.md, claims/ and results/) and state (config.json, an empty queue.json and
comments.json). Existing config, queue, comments, claims and results are left alone; the workflows are replaced. No
code goes into the results repository: the workflows check out the tool at a pinned commit."""

import json
import shutil
from pathlib import Path

from . import ROOT, formats

TEMPLATE = ROOT / "results_repo"


def export(main, state, repository=None):
    main, state = Path(main), Path(state)
    main.mkdir(parents=True, exist_ok=True)
    state.mkdir(parents=True, exist_ok=True)
    shutil.copytree(TEMPLATE / ".github", main / ".github", dirs_exist_ok=True)
    if not (main / "README.md").exists():
        shutil.copy2(TEMPLATE / "README.md", main / "README.md")
    for name in ("claims", "results"):
        (main / name).mkdir(exist_ok=True)
        (main / name / ".gitkeep").touch()
    if not (state / "config.json").exists():
        shutil.copy2(TEMPLATE / "state" / "config.json", state / "config.json")
    config = json.loads((state / "config.json").read_text())
    if repository:
        config["repository"] = repository
        (state / "config.json").write_text(json.dumps(config, indent=2) + "\n")
    formats.check_config(config)
    if not (state / "queue.json").exists():
        (state / "queue.json").write_text(json.dumps(formats.empty_queue(config["repository"]), indent=2) + "\n")
    if not (state / "comments.json").exists():
        (state / "comments.json").write_text(json.dumps(formats.empty_comments(), indent=2) + "\n")
    return main, state
