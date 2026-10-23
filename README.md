# anyps5-title-runs

Test AnyPS5 pull requests on your own games and hardware. A pull request's head is built, run in a sandbox on a game
you own, and timed against main the way the project's performance reports ask; the result goes to the pull request,
or stays on your computer until you post it yourself. Developers get timings on hardware and games they don't have.

Python 3.11 or later, the standard library only; the window needs PySide6. Linux, with bubblewrap for the sandbox; the
Windows paths are written but not run yet.

Tests come from two places:

- **The queue**: maintainers install one GitHub App and keep one public results repository with one scheduled
  workflow. They queue a pull request's head with a label or a `/title-test` command. Testers sign in through the App,
  register their machine, and report as comments on per-job issues.
- **Local tests**: pull requests you pick, tested on your computer against the project's main, with a report in the
  project's own form that stays there until you post it. A project that hasn't set up the queue gets local tests only.

DESIGN.md says what the tool is for and why it is as it is, FORMATS.md describes the results repository's files and
the testers' comments, and docs/CLI.md every command.

## Getting started

```
git clone https://github.com/CPritch/anyps5-title-runs ~/src/anyps5-title-runs
sudo pacman -S bubblewrap                    # or your distribution's package; and PySide6 for the window
~/src/anyps5-title-runs/title-runs window    # a new config: the first-run walkthrough sets it up
```

The walkthrough covers what the tool does and what leaves the computer, the sandbox and what it doesn't protect
against, when tests may run (idle where the computer can tell, otherwise set hours; on mains power; a pause while
something is fullscreen), your games and the AnyPS5 clone, signing in with GitHub, and registering the machine.
Nothing runs before it is done.

For a project that hasn't set up the queue, a config with `[results] url = ""` and `app` (the GitHub App to sign in
with) runs local tests only: nothing to register, nothing sent (DESIGN.md, "Local tests only"). Open it with
`title-runs window --config FILE`.

## The command line

`title-runs` does what the window does, from the same config and state folder, with the window open or without it:

```
title-runs status                    what this computer is doing, and anything to fix
title-runs testing now               the testing switch: off, schedule or now
title-runs local add 4287            a pull request for your local tests
title-runs run --once                one test now, whatever the switch says
title-runs local report 4287         its report: the link to post it on first, then the text
title-runs local files 4287          the traces to drag into the comment
title-runs local posted 4287         record that you posted it
title-runs help local report         what a command does, what it changes, its JSON and examples
```

For agents and scripts: every command takes `--json` (one object; one per line for `run` and `sign-in`), and exits
0 when done, 1 when it couldn't (the message says why) and 2 when it was written wrong. The commands that write to
GitHub, as you, are marked in `title-runs help`; nothing else posts anything. A setting changed on the command line
reaches an open window within a few seconds, one test runs on a computer at a time, and `title-runs stop` ends a test
the window started. docs/CLI.md has every command, made from the commands themselves.

## The window

- **Home**: the testing switch (Off, On schedule, Now), the test running with its step and the game itself inside the
  window, what's next, and the results.
- **Local tests**: add a pull request by number or link, follow people, test again, the fixes carried on both sides
  and the main they're measured against. Each result has a report window: the link to post it on, the text to copy,
  the traces to drag into the comment, and Mark as posted.
- **All pull requests** (the advanced view) and **Settings**: your account and the machine's registration, the testing
  link, the sandbox check, what's shared, when to test, your games and their scenarios, and the logs.
- **Maintainer tools**, for maintainers: the queue with what each test still wants, the machines and when each last
  reported, and registrations to approve or decline.

Closing the window quits and ends a running test, unless it is set to keep running in the tray. The screenshots in
`docs/screens/` are of the round-3 window, which has changed since.

## Local tests

Main is pinned for 12 hours, so the pull requests tested together are measured against the same main, built and warmed
up once. Fixes (pull requests main needs to run your games) are merged onto both sides. Only a head its author pushed
is tested. The report is in the project's form: what ran where, main against main plus the pull request in the order
A B A B, the summary lines, one trace per run under GitHub's 25 MB and each trace's digest. Posting is yours: a result
not posted goes stale when the pull request gets a new head, closes or merges, or after 48 hours. Testing a head again
keeps the earlier result. DESIGN.md has the details ("Local tests and the testing switch", "Reports with their traces").

## The queue (maintainers)

What a maintainer sets up (`results_repo/README.md`, and `docs/first-real-test.md` for the first one): one GitHub App
made from its manifest with `title-runs app create` (no webhook, device flow on; Actions read, Issues and Pull
requests read and write, Metadata read) installed on AnyPS5 and on one public results repository, whose only secret
is the App's private key. Nothing to host, no paid feature, no token per tester. `title-runs relay poll --dry-run`
reads the real repositories and records what the workflow would write, without writing.

The results repository's one workflow, `relay` (`results_repo/.github/workflows/relay.yml`, code in
`title_runs/relay/`), runs every 5 minutes and on demand, at the tool's commit that `config.json` pins:

1. **Queue.** It reads AnyPS5's label events and comments as the App. A maintainer's `title-test` label pins the PR's
   head, if that head was pushed before the label; the push time and pusher come from the PR's earliest workflow run
   for that head, since a label event carries no SHA. A head with no workflow run needs `/title-test sha=<sha>`; a
   refused label is removed, and the App says why in a new comment. `/title-test [high|normal|low] [titles=..] [hw=..] [machines=N]
   [sha=..] | stop` sets options and can pin any commit. Each queued head gets a job issue in the results repository.
2. **A push after approval** carries the approval over if the new head has the approved head's patch-ids (a rebase),
   or if a collaborator who isn't the author pushed it. Otherwise the approval expires: the App removes the label
   and says in a new comment which commit expired it. A maintainer adds the label again to queue the new head; the
   notice then moves into the comment's earlier-heads history.
3. **Registrations.** A tester's client opens a `Machine: <login>/<machine>` issue. A maintainer approves it by adding
   the label `approved` (`declined` turns it down), on GitHub or with Approve in the client's Overview tab.
4. **Results.** A claim and a result are comments on the job issue from the tester's own account. Nothing else gets a
   reply: what the workflow doesn't use is counted in the Overview. The workflow takes
   a result only from a registered machine with an earlier, unexpired claim on the same job and head, writes it to
   `results/`, and edits the App's comment on the PR. It posts a new comment instead when an outcome or a verdict
   changes.
5. **Overview.** It keeps an "Overview" issue up to date: the queue with coverage per class and title and what is
   still wanted, approvals a push expired, machines and when each last reported, and pending registrations.

Verdicts (`title_runs/verdict.py`, DESIGN.md "Verdicts"): on one machine a difference counts when it exceeds both
spreads and 1 % of main's p50. Machines of one class (GPU model, driver branch, OS) are combined by their main-vs-PR
differences, never their raw frame times: "faster on 3 of 3 <class> machines, median -0.30 ms". A borderline class
asks the scheduler for one more machine of it.

The client (`title_runs/client.py`) reads the results repository's public checkout and never pushes to it. It picks
the best-scoring job (`schedule.py`), claims it with a comment, fetches the approved SHA and main, merges them
locally, checks the queue again, builds and runs in the sandbox, and reports with a comment.

### The stand-in

```
python3 -I title-runs standin label 8104 --by CPritch --root DIR          # a maintainer's label on AnyPS5
python3 -I title-runs standin tick --root DIR                             # one run of the relay workflow
python3 -I title-runs standin codes --root DIR                            # device codes waiting to be entered
python3 -I title-runs standin authorize CODE --as LOGIN --root DIR        # a tester enters the code on GitHub
python3 -I title-runs standin approve ISSUE --by CPritch --root DIR       # a maintainer's approved label
python3 -I title-runs standin push 8104 SHA --by Celegans12 --root DIR    # a push to the PR, with its workflow run
python3 -I title-runs --config FILE run --once                            # claim, build, run, report
```

`title_runs/standin.py` keeps a fake GitHub (`github.json`: both repositories, accounts, permissions, the device
flow), the results repository (`results.git`), a stand-in AnyPS5 remote, and the outbox, where every write anyone
makes is recorded with who made it. `title_runs/gh.py` is the one interface to GitHub. It has the REST implementation
the workflow and the client use on GitHub, and the fake.

## What a test does

A test is one head of a pull request, from the queue (a maintainer approved it) or from the tester's local tests:

1. **Job**: fetch `refs/pull/N/merge` (GitHub's merge of the PR into its base branch) and the head;
   build the merge and main at the merge's base (its first parent) in two worktrees of the tester's clone, with build
   directories that are kept and rebuilt incrementally. A PR without a merge ref (it does not merge cleanly) is
   reported as such.
2. **Run**, per title, in the sandbox (below):
   - a title with a route (`routes/<ID>.json`): the harness's measurement protocol, main against the PR:
     warm-ups only for a build whose caches are cold, each running the route and then staying in the scene until its
     last 60 s built no pipelines (at most 20 minutes); one window from the settle points, 60 s or as many presents
     as fit a 20 MB trace (GitHub takes attached files up to 25 MB, and the project's form asks for each trace); two
     counted runs per side in the order A B A B, checked by the harness's `capture.py` (one window summary line,
     complete totals, no load frame, no pipeline build in the window, frame dumps stopped before the window), a run
     that does not count repeated once; main's `tools/performance_compare.py` per pair. The verdict rule: a
     difference counts when it is larger than both sides' spreads.
   - a title without a route: #7264's `prepare()` and `run_title()`, unchanged: boot twice (cold, then warm) for the
     title's `boot_seconds` (default: titles.json's `seconds`, else 60) and classify each run (`relink-failed`,
     `crashed`, `exited`, `stalled`, `blank`, `rendering`). `run_title()` is given a wrapper that starts the title
     in the sandbox, and an environment with only the title's variables.
3. **Result**: a queued test's result goes to the job's issue in the results repository as a comment from the tester's
   account, and the workflow puts it on the PR. A local test's report, in the project's own form with its traces,
   stays on this computer; the tester posts it themselves, or not.

## The config

The window writes it; `config.example.toml` explains every key. `source.repo_dir` is a clone of the repository with its submodules checked out; jobs make worktrees from it and fill
their submodules from its submodule repositories at each side's pins (nested ones included). Without a `.git` in the
worktree's `3rdparty/ffmpeg-core`, CMake needs `-DFFMPEG_PREBUILT_DIR=<an unpacked ffmpeg package for the pin>` in
`source.cmake_args`.

Per title: the dump directory (an extracted package: `eboot.bin`, `sce_sys/param.json`), optionally a route, seed
files (save data and settings copied into the title's private game directory before its first run), `app0_skip`
(package entries to leave out of `app0`), the Graphics Mode the seeded settings select (for the report) and extra
environment.

## Routes

A route is data (JSON): pad steps and frame-state conditions to a named scene, as the harness's `nav.sh` does. Frames
come from `APS5_DUMP_FRAMES`, classified by the harness's `frame_state.py` (black, title, calibration, colour);
presses go through main's `tools/pad_input.py`; load detection reads the 10 s summaries (`steady.py`). The step
vocabulary is in `title_runs/route.py`. `routes/PPSA04263.json` is GTA V's: title, calibration, landing page, two R1
presses to the Story tab, Resume Story, then until the Story has loaded. Timed runs stop the route after the
Resume Story press (`timed_stop_after`) and wait for the window.

## Scenarios

Every timed run is in a scenario (`scenarios/<ID>/<id>.json`, `title_runs/scenarios.py`): one specific run of a title,
which may or may not load a save. A scenario names the route that gets there, the report's words for what is on screen,
the save if it has one (downloaded from its source and checked against its sha256, never stored in this repository), a
button pressed every few seconds to keep the title's idle camera from turning if it needs one, and the scene's colours,
which each run is checked against. A title runs in one scenario (`scenario = "<id>"` in its section, or the Titles
page), its default when none is named. GTA V's are `prologue` (the default: a new game, no save) and `franklins-house`
(Franklin at his front door in Vinewood Hills, from Apollo's PS4 100% save).

## The trust model

A followed PR's code runs on the tester's machine. What stands between that code and the machine:

- **Which heads run.** A queued test is a commit a maintainer approved (a later push expires the approval). A local
  test runs only a head the PR's own author pushed (the PR's first workflow run for that head names its pusher). Any
  other head runs only through the trust dialog, which needs the tester to type the author's name.
- **The build runs in the build sandbox** (round 2): the same bubblewrap setup without GPU, display or network; the
  source tree, its git directory and prebuilt dependencies read-only, only the build directory writable. Fetching
  the commit, main and submodule pins happens before, outside it. A malicious PR still runs its code at build time,
  inside the sandbox.
- **The title runs in bubblewrap:** `/usr`, `/etc`, `/sys` read-only; an empty `/home`, `/tmp` and `/run`; its own PID
  namespace (the host's processes are not visible in its `/proc`); a minimal `/dev` with only the GPU's device nodes (`/dev/dri`, `/dev/nvidia*`); the display sockets
  (Wayland, X11) and nothing else of the session (no D-Bus, no audio server, no SSH agent); no network (its own
  network namespace). The dump, `app0` (hard links to the dump's files) and `libs` are read-only; only the title's
  game directory, its caches and the run directory are writable.

What this does not protect against:

- a driver or kernel exploit: the GPU's device nodes and the display server are reachable from inside, so a bug in
  the GPU driver, the kernel or the compositor can be used to leave the sandbox;
- a tester's sign-in: it can open issues and comment in the results repository as the tester, nothing more. The
  workflow uses only what comes from registered machines with a live claim, and nobody but the workflow and the
  maintainers writes the repository's files;
- the display: a title can draw on the tester's screen and read what the compositor lets any client read;
- resource exhaustion: no CPU, memory or disk limits are set beyond the core-dump limit;
- `sandbox.mode = "none"`, which the tester can set explicitly; every report then says the sandbox was off.

## What leaves the machine

A queued test's result, as a comment from the tester's account on its job's issue in the results repository: timings
(frame times, GPU time per present), the summary lines AnyPS5 prints (build commit, GPU, driver, OS, CPU, memory,
environment switches, top phases), outcome classes, the first error line of a title that does not render, the machine
name, and, when enabled, a screenshot of the scene. A local test sends nothing: its report stays on this computer.
Never game files, save data or the dump's contents. Pull requests and the results repository are read from GitHub.

## Built on

- `vendor/title_run/`: #7264's `tools/title_run.py` (LeandroLP23), unchanged, at c2dce8dd3: discovery, relinking and
  layout (`prepare()`), outcome classes, `summary.json`, the generic boot-and-classify run.
- `vendor/gtav_harness/`: the harness's `frame_state.py`, `steady.py` and `capture.py`, unchanged, at ef6636d: frame
  states, load detection, the Performance report form's protocol (window, warm caches, counts / not counted, quiet).
- Main's `tools/performance_compare.py`, `tools/trace_digest.py` and `tools/pad_input.py`, from each job's checkout of
  main's base commit.

What this repository adds is listed in `SUGGESTIONS.md`, with the parts that could go back to #7264.

## Tests

```
python3 -I -m unittest discover -s tests -t tests
```

The client, the workflow (relay) against the stand-in, local tests and their reports, scenarios, the verdict rules,
the timed window, the sandboxes, the formats, and the window's model and pages (offscreen).

## License

GNU General Public License version 2 only, the same as AnyPS5 (`LICENSE` is AnyPS5's). `vendor/title_run/` is
#7264's code from AnyPS5 under that licence; `vendor/gtav_harness/` is from CPritch/gtav-harness, included under it
too.
