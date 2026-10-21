"""The round-3 end-to-end run on the laptop against the stand-in, one step at a time (python3 -I drive.py STEP):

  setup       a fresh stand-in (#8104 at 69ac2e155, main d97361bd0); the laptop's, the maintainer's and the twin's configs
  onboard     the laptop's tester goes through the walkthrough (offscreen, every page grabbed), signs in, registers
  approve     the maintainer signs in, sees the registration in the Overview tab and presses Approve; the workflow runs
  label       the maintainer adds title-test to #8104; the workflow runs
  (the run)   python3 -I title-runs client --config laptop.toml run-once --ignore-schedule   (the real build and A/B)
  running     grabs of the window and tray while the job runs
  result      the workflow runs: the result is accepted, the PR comment and the overview show it
  synthetic   a second machine of the laptop's class onboards, is approved and reports SYNTHETIC numbers (today's laptop
              run with the PR's p50 lowered by 1.5 ms): the class disagrees and turns borderline
  twin        a third machine of the class (laptop-2) is asked for, onboards and reports the laptop's round-2 run of the
              same commit 69ac2e155: the class settles
  push        the author pushes 8118a04e4; the workflow runs: the approval expires and the App removes the label
  refix       after the overview fix: a workflow run, and the maintainer queues 8118a04e4 with the label again
  collect     the outbox, the workflow's log and state, into this folder

Each step appends to steps.log here. Screens go to screens/ here."""

import datetime
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
TOOL = HERE.parent.parent
sys.path.insert(0, str(TOOL))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from title_runs import client as clients, config as configs, formats, standin  # noqa: E402

R3 = Path.home() / "games" / "title-runs-r3"
STAND = R3 / "standin"
STATE = Path.home() / "games" / "title-runs-state"
ROUND2 = Path.home() / "games" / "title-runs-standin" / "laptop.toml"
CLONE = Path.home() / "src" / "AnyPS5"
DUMPS = Path.home() / "Documents" / "GTAVRipPersonal"
MAIN, HEAD, SECOND = "d97361bd0df0a54b11570602391aa003bff31047", "69ac2e155ad018ed1fb9028d2028d15999a8571e", "8118a04e4ff4cd817ad25fab2d69eaafea50ae6f"
TITLE = "perf(agc): stage the written elements of address-based compute builds in device memory"
SCREENS = HERE / "screens"
TESTER, TWIN, MAINTAINER = "standin-tester", "standin-tester-2", "CPritch"


def log(text):
    line = f"{datetime.datetime.now(datetime.timezone.utc):%Y-%m-%dT%H:%M:%SZ} {text}"
    print(line, flush=True)
    with open(HERE / "steps.log", "a") as stream:
        stream.write(line + "\n")


def stand():
    return standin.Standin(STAND)


def tick(why):
    changed = stand().tick()
    log(f"workflow run ({why}): changed {', '.join(f'#{n}' for n in changed) or 'nothing'}")


def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def engine(name, sync=True):
    from title_runs.ui.app import Engine
    eng = Engine(configs.load(R3 / f"{name}.toml"))
    if name != "maintainer":
        eng.client.info = dict(eng.config.machine_info)
    eng.load(sync=sync)
    return eng


def grab_tab(eng, tab, name):
    from title_runs.ui.app import grab
    from title_runs.ui.window import MainWindow
    window = MainWindow(eng)
    window.refresh()
    window.show()
    window.tabs.setCurrentWidget(getattr(window, tab))
    path = grab(window, SCREENS / f"{name}.png")
    window.close()
    log(f"screen {path.name}")
    return window


def sign_in(eng, login):
    flow = eng.client.flow()
    device = flow.start()
    stand().authorize(device["user_code"], login)
    flow.poll(device)
    log(f"{login} signed in (device code {device['user_code']})")


def pr_comment():
    """The App's comment on #8104 as it now stands."""
    fake = stand().github()
    notes = [c for c in fake.data["repos"][standin.ANYPS5]["comments"].values() if c["issue"] == 8104 and c["user"] == standin.APP_BOT]
    return notes[-1]["body"] if notes else ""


def save_comment(name):
    (HERE / "comments").mkdir(exist_ok=True)
    (HERE / "comments" / f"{name}.md").write_text(pr_comment())
    log(f"PR comment saved as comments/{name}.md")


def setup():
    if STAND.exists():
        raise SystemExit(f"{STAND} exists")
    for old, new in ((STATE / "client", STATE / "client-round2"), (STATE / "jobs" / "8104-69ac2e155ad0", STATE / "jobs" / "8104-69ac2e155ad0.round2")):
        if old.exists() and not new.exists():
            old.rename(new)
            log(f"moved round 2's {old} to {new.name}")
    tool = subprocess.run(["git", "-C", str(TOOL), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    standin.create(STAND, [MAINTAINER], CLONE, MAIN, [{"number": 8104, "title": TITLE, "author": "Celegans12", "head": HEAD, "head_ref": "perf/agc-staging"}],
                   {MAINTAINER: "admin", "Celegans12": "read"}, tool)
    log(f"stand-in at {STAND}: #8104 at {HEAD[:9]} by Celegans12, main {MAIN[:9]}, maintainers [{MAINTAINER}], tool {tool[:9]}")
    text = ROUND2.read_text()
    text = text.replace('''[results]
url = "/home/charlie/games/title-runs-standin/results.git"
token_env = "TITLE_RUNS_RESULTS_TOKEN"
state_branch = "state"''', f'''[results]
url = "{STAND / 'results.git'}"
github = "standin:{STAND / 'github.json'}"''')
    text = text.replace('remote = "/home/charlie/games/title-runs-standin/anyps5.git"', f'remote = "{STAND / "anyps5.git"}"')
    text = text.replace('name = "CPritch"\n', 'name = ""\n')
    assert f'url = "{STAND / "results.git"}"' in text and str(STAND / "anyps5.git") in text
    (R3 / "laptop.toml").write_text(text)
    twin = text.replace(f'state_dir = "{STATE}"', f'state_dir = "{R3 / "twin-state"}"').replace('machine = "laptop"', 'machine = "laptop-2"')
    (R3 / "twin.toml").write_text(twin)
    from title_runs.ui.app import new_config
    new_config(R3 / "maintainer.toml", str(STAND / "results.git"), f"standin:{STAND / 'github.json'}", R3 / "maintainer-state")
    log("configs: laptop.toml (round 2's machine and title settings, not onboarded), twin.toml (laptop-2), maintainer.toml")


def onboard():
    app()
    from title_runs.ui import shots
    eng = engine("laptop")
    SCREENS.mkdir(exist_ok=True)
    saved = shots.walkthrough(eng, SCREENS, str(DUMPS), lambda code: (stand().authorize(code, TESTER), log(f"{TESTER} entered {code}")))
    log("walkthrough: " + ", ".join(p.name for p in saved))
    state, record = eng.client.registration()
    log(f"{TESTER}/laptop: {state}, issue #{record['issue']}; ready: {eng.client.ready()}")
    tick("registration")
    eng.load(sync=True)
    grab_tab(eng, "queue", "tester-1-queue-not-ready")


def approve():
    app()
    eng = engine("maintainer")
    eng.client.finish_onboarding({"maintainer": True})
    sign_in(eng, MAINTAINER)
    eng.load(sync=True)
    window = grab_tab(eng, "overview", "maintainer-1-pending")
    window.overview.refresh()
    item = window.overview.pending.topLevelItem(0)
    button = window.overview.pending.itemWidget(item, 3).layout().itemAt(0).widget()
    log(f"maintainer's Overview: pending {item.text(1)} ({item.text(0)}), Approve enabled: {button.isEnabled()}")
    button.click()
    log(f"{MAINTAINER} pressed Approve: {window.overview.pending.topLevelItem(0).text(3)}")
    tick("approval")
    eng.load(sync=True)
    grab_tab(eng, "overview", "maintainer-2-approved")
    tester = engine("laptop")
    log(f"laptop: {tester.client.registration()[0]}; ready: {tester.client.ready()}")


def label():
    app()
    stand().label(8104, MAINTAINER)
    log(f"{MAINTAINER} added title-test to #8104")
    tick("label")
    eng = engine("maintainer")
    grab_tab(eng, "overview", "maintainer-3-queued")
    tester = engine("laptop")
    entry = tester.client.repo.queue()["entries"][0]
    log(f"queue: #{entry['pr']} {entry['head'][:9]} approved by {entry['approval']['by']} via {entry['approval']['via']}, job issue #{entry['issue']}")
    grab_tab(tester, "queue", "tester-2-queue-ready")
    save_comment("1-queued")


def running():
    app()
    from title_runs.ui.app import screenshots
    eng = engine("laptop", sync=False)
    for path in screenshots(eng, SCREENS, "tester-3-running-"):
        log(f"screen {path.name}")


def result():
    app()
    tick("the laptop's result")
    eng = engine("maintainer")
    grab_tab(eng, "overview", "maintainer-4-one-result")
    save_comment("2-laptop-result")
    tester = engine("laptop")
    grab_tab(tester, "queue", "tester-4-reported")


def machine(name, tester, numbers, why):
    """Another machine of the laptop's class: a real client with its own sign-in, registration, claim and result
    comment; job.run is replaced by numbers."""
    app()
    config_path = R3 / f"{name}.toml"
    if not config_path.exists():
        text = (R3 / "twin.toml").read_text()
        config_path.write_text(text.replace(f'state_dir = "{R3 / "twin-state"}"', f'state_dir = "{R3 / (name + "-state")}"')
                               .replace('machine = "laptop-2"', f'machine = "{name}"'))
    config = configs.load(config_path)
    eng_client = clients.Client(config, log=lambda text: log(f"{name}: {text}"), info=dict(config.machine_info))
    eng_client.repo.sync()
    eng_client.finish_onboarding({"simulated": True})
    flow = eng_client.flow()
    device = flow.start()
    stand().authorize(device["user_code"], tester)
    flow.poll(device)
    issue = eng_client.register()
    log(f"{tester}/{name} (class {formats.class_key(eng_client.machine_class)}) registered: #{issue}")
    tick(f"{name}'s registration")
    maintainer = engine("maintainer")
    log(f"{MAINTAINER} approves #{issue}: {maintainer.decide_registration(issue, 'approved') or 'label added'}")
    tick(f"{name}'s approval")
    eng_client.repo.sync()
    log(f"{name} ready: {eng_client.ready()}")
    for choice in eng_client.ranked(sync=False):
        log(f"{name}'s score for #{choice.entry['pr']}: {choice.score:.2f} ({'; '.join(choice.reasons)})")
    sides = numbers["titles"]["PPSA04263"]["verdict"]["sides"]
    log(f"{name}'s numbers ({why}): main p50 {sides['A']['p50']}, PR p50 {sides['B']['p50']}")
    with mock.patch("title_runs.job.run", return_value=numbers):
        data = eng_client.run(8104, HEAD)
    log(f"{name} reported: {data['status']}")
    tick(f"{name}'s result")
    maintainer.load(sync=True)
    return maintainer


def synthetic():
    numbers = json.loads((STATE / "jobs" / "8104-69ac2e155ad0" / "results.json").read_text())
    numbers["machine"] = "synthetic"
    title = numbers["titles"]["PPSA04263"]
    title["scene"] = "SYNTHETIC: the laptop's run of 69ac2e155 today with the PR's p50 lowered by 1.5 ms"
    title["verdict"]["sides"]["B"]["p50"] = [round(v - 1.5, 3) for v in title["verdict"]["sides"]["B"]["p50"]]
    title["ab"]["runs"] = []  # no summary lines: they would contradict the lowered p50
    maintainer = machine("synthetic", "standin-tester-3", numbers, "synthetic, not measured: today's laptop numbers, PR p50 -1.5 ms")
    grab_tab(maintainer, "overview", "maintainer-5-synthetic-second")
    save_comment("3-synthetic-second")


def twin():
    numbers = json.loads((STATE / "jobs" / "8104-69ac2e155ad0.round2" / "results.json").read_text())
    numbers["machine"] = "laptop-2"
    maintainer = machine("laptop-2", TWIN, numbers, "the laptop's round-2 run of the same commit 69ac2e155, measured 2026-10-21 12:27 UTC")
    grab_tab(maintainer, "overview", "maintainer-6-third")
    save_comment("4-third")


def push():
    app()
    stand().push(8104, SECOND, "Celegans12")
    log(f"Celegans12 pushed {SECOND[:9]} to #8104")
    tick("the push")
    fake = stand().github()
    log(f"#8104 labels now: {fake.data['repos'][standin.ANYPS5]['pulls']['8104']['labels']}")
    eng = engine("maintainer")
    grab_tab(eng, "overview", "maintainer-7-expired")
    save_comment("5-expired")
    tester = engine("laptop")
    grab_tab(tester, "queue", "tester-5-after-push")
    grab_tab(tester, "settings", "tester-6-settings")
    grab_tab(tester, "schedule", "tester-7-schedule")


def refix():
    """After the overview fix (a reported machine shown as running): one more workflow run and the overview again."""
    app()
    log(f"overview fix committed ({subprocess.run(['git', '-C', str(TOOL), 'rev-parse', '--short', 'HEAD'], capture_output=True, text=True).stdout.strip()})")
    tick("after the overview fix")
    stand().label(8104, MAINTAINER)
    log(f"{MAINTAINER} added title-test to #8104 again, to queue {SECOND[:9]}")
    tick("the label again")
    eng = engine("maintainer")
    grab_tab(eng, "overview", "maintainer-8-requeued")
    save_comment("6-requeued")


def collect():
    for name in ("outbox",):
        shutil.copytree(STAND / name, HERE / name, dirs_exist_ok=True)
    shutil.copy2(STAND / "relay.log", HERE / "relay.log")
    state = HERE / "state"
    shutil.rmtree(state, ignore_errors=True)
    state.mkdir()
    archive = subprocess.run(["git", "--git-dir", str(STAND / "results.git"), "archive", "main"], capture_output=True, check=True).stdout
    subprocess.run(["tar", "-x", "-C", str(state)], input=archive, check=True)
    data = json.loads((STAND / "github.json").read_text())
    lines = []
    for name in (standin.RESULTS, standin.ANYPS5):
        repo = data["repos"][name]
        lines += [f"# {name}", ""]
        for number, issue in sorted(repo.get("issues", {}).items(), key=lambda x: int(x[0])):
            lines += [f"## #{number} {issue['title']} (by {issue['user']}, {issue['created_at']}, {issue['state']}, labels {issue.get('labels', [])})", ""]
        for event in repo.get("events", []):
            lines.append(f"- event {event['created_at']} {event['actor']} {event['event']} {event['label']} on #{event['issue']}")
        lines.append("")
        for note in sorted(repo.get("comments", {}).values(), key=lambda c: c["id"]):
            first = note["body"].splitlines()[0] if note["body"] else ""
            lines.append(f"- comment {note['id']} on #{note['issue']} by {note['user']} at {note['created_at']}: {first[:120]}")
        lines.append("")
    (HERE / "github.md").write_text("\n".join(lines))
    log(f"collected the outbox ({len(list((HERE / 'outbox').iterdir()))} files), relay.log, the results repository's main and github.md "
        f"(every issue, label event and comment in the fake GitHub: the outbox missed the testers' and the maintainer's own-sign-in writes "
        f"until {subprocess.run(['git', '-C', str(TOOL), 'rev-parse', '--short', 'HEAD'], capture_output=True, text=True).stdout.strip()})")


if __name__ == "__main__":
    globals()[sys.argv[1]]()
