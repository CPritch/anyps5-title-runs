#!/usr/bin/env python3
"""The README's demo of a second head: copy the state, then write a fixture listing in which PR N has a new head, and
a results file for that head (the real head's measurements, marked as simulated).

  demo/simulate_head.py --config config.toml --pr 8104 --out STATE_COPY
  ./title-runs --config <copy's config> poll --fixture STATE_COPY/fixture-listing.json --at <seen>
  ./title-runs --config <copy's config> poll --fixture STATE_COPY/fixture-listing.json --at <seen + debounce>
  ./title-runs --config <copy's config> publish 8104 --results STATE_COPY/fixture-results.json

The copy's config is written beside the copy (config.toml with state_dir pointing at it). Nothing here talks to
GitHub or builds anything.
"""

import argparse
import datetime
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from title_runs import config as configs  # noqa: E402
from title_runs.state import State  # noqa: E402


def fake_sha(text):
    return hashlib.sha1(text.encode()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--pr", type=int, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    config = configs.load(args.config)
    if args.out.exists():
        raise SystemExit(f"{args.out} exists")
    shutil.copytree(config.state_dir, args.out, ignore=shutil.ignore_patterns("trees", "builds", "games", "caches", "runs"))
    text, count = re.subn(r'(?m)^state_dir = .*$', f'state_dir = "{args.out}"', args.config.read_text())
    if count != 1:
        raise SystemExit("could not point the copied config at the copy")
    (args.out / "config.toml").write_text(text)

    state = State(args.out / "state.json")
    current = state.current(args.pr)
    real = json.loads((config.state_dir / "jobs" / f"{args.pr}-{current['head'][:12]}" / "results.json").read_text())
    listing = json.loads((args.out / "cache" / "pull-requests.json").read_text())
    pr = listing["prs"][str(args.pr)]
    seen = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)
    head = fake_sha(f"simulated head of #{args.pr} after {current['head']}")
    pr = {**pr, "headRefOid": head, "updatedAt": seen.isoformat().replace("+00:00", "Z")}
    pr["commits"] = {"nodes": [{"commit": {"oid": head, "committedDate": (seen - datetime.timedelta(minutes=1)).isoformat().replace("+00:00", "Z"),
                                           "author": pr["commits"]["nodes"][0]["commit"]["author"]}}]}
    (args.out / "fixture-listing.json").write_text(json.dumps({"nodes": [pr]}, indent=2))

    results = {**real, "head": head, "merge": fake_sha(f"simulated merge of {head}"),
               "started": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
               "simulated": f"head `{head[:9]}` does not exist; these are head `{current['head'][:9]}`'s measurements again, "
                            f"to show how the comment is edited and the earlier head moves to the history table"}
    (args.out / "fixture-results.json").write_text(json.dumps(results, indent=2))
    later = seen + datetime.timedelta(minutes=config.debounce_minutes + 1)
    print(f"copy: {args.out}\nhead: {head}\nseen: {seen.isoformat()}\nready after: {later.isoformat()}")


if __name__ == "__main__":
    main()
