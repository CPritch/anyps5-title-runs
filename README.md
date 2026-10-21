# anyps5-title-runs

Volunteers who own game dumps follow AnyPS5 pull requests. Every new head of a followed PR is built and run on their
titles automatically, and a bot keeps one comment per PR and machine up to date with the results. Developers get title
runs on hardware and games they do not have, without asking each time.

Python 3.11 or later; the engine and the workflows use the standard library only, the tray and the window PySide6.
Linux (bubblewrap for the sandbox); the client's platform code has Windows paths written but not yet run.

DESIGN.md describes the tool we are aiming for, FORMATS.md the results repository's files and the testers' comments.
There are two ways to drive the engine:

- **The client and the results repository** (round 3, below): maintainers install one GitHub App and keep one public
  results repository with one scheduled workflow. They queue a PR's head with a label or a `/title-test` command.
  Testers sign in through the App, register their machine, and report as comments on per-job issues. Until the App
  and the repository exist, `title-runs standin` plays GitHub, the results repository and its workflow on one machine.
- **The tester's own poller** (round 1, "What it does" and after): one tester follows PRs from a GraphQL listing and
  posts with a bot token. Kept for reference; DESIGN.md replaces its trust and posting.

## The client and the results repository

What a maintainer sets up (`results_repo/README.md`): one GitHub App (no webhook, device flow on; Issues and Pull
requests read and write, Metadata read) installed on AnyPS5 and on one public results repository, whose only secret
is the App's private key. Nothing to host, no paid feature, no token per tester.

The results repository's one workflow, `relay` (`results_repo/.github/workflows/relay.yml`, code in
`title_runs/relay/`), runs every 5 minutes and on demand, at the tool's commit that `config.json` pins:

1. **Queue.** It reads AnyPS5's label events and comments as the App. A maintainer's `title-test` label pins the PR's
   head, if that head was pushed before the label; the push time and pusher come from the PR's earliest workflow run
   for that head, since a label event carries no SHA. A head with no workflow run needs `/title-test sha=<sha>`; a
   refused label is removed, and the App says why in a new comment. `/title-test [high|normal|low] [titles=..] [hw=..] [machines=N]
   [sha=..] | stop` sets options and can pin any commit. Each queued head gets a job issue in the results repository.
2. **A push after approval** carries the approval over if the new head has the approved head's patch-ids (a rebase),
   or if a collaborator who isn't the author pushed it. Otherwise the approval expires: the App removes the label,
   and its comment on the PR says which commit expired it. A maintainer adds the label again to queue the new head.
3. **Registrations.** A tester's client opens a `Machine: <login>/<machine>` issue. A maintainer approves it by adding
   the label `approved` (`declined` turns it down), on GitHub or with Approve in the client's Overview tab.
4. **Results.** A claim and a result are comments on the job issue from the tester's own account. The workflow takes
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

### The window

`title-runs ui --config FILE` starts the tray and the window. On first open (`--config NEW --results URL` makes a new
config) it shows the walkthrough. The walkthrough covers what the tool does and what leaves the machine, the sandbox
and what it doesn't protect against, and when work may run: idle where the machine can tell, otherwise set hours,
plus mains power and a fullscreen pause. Then come the dumps and the AnyPS5 clone, signing in with GitHub by device
code, and registering the machine. Nothing runs until the walkthrough is done, the tester is signed in and a
maintainer has approved the machine.

The window has six tabs:
- **Queue:** a banner says what keeps the machine from taking jobs, then running, up next with the score's reasons,
  waiting for you and recently posted.
- **Overview:** the maintainers' view, as above, with Approve and Decline for maintainers.
- **Pull requests**, **Schedule** and **Titles**.
- **Settings:** account, registration, the results repository, the sandbox self-test, trusted authors and logs.

`Run…` on a PR no maintainer queued opens the trust dialog. Screenshots are in `docs/screens/`. Without the window:
`title-runs client --config FILE status|sign-in|register|queue|next|run-once|daemon`.

### The stand-in

```
python3 -I title-runs standin label 8104 --by CPritch --root DIR          # a maintainer's label on AnyPS5
python3 -I title-runs standin tick --root DIR                             # one run of the relay workflow
python3 -I title-runs standin codes --root DIR                            # device codes waiting to be entered
python3 -I title-runs standin authorize CODE --as LOGIN --root DIR        # a tester enters the code on GitHub
python3 -I title-runs standin approve ISSUE --by CPritch --root DIR       # a maintainer's approved label
python3 -I title-runs standin push 8104 SHA --by Celegans12 --root DIR    # a push to the PR, with its workflow run
python3 -I title-runs client --config FILE run-once --ignore-schedule      # claim, build, run, report
```

`title_runs/standin.py` keeps a fake GitHub (`github.json`: both repositories, accounts, permissions, the device
flow), the results repository (`results.git`), a stand-in AnyPS5 remote, and the outbox, where every write anyone
makes is recorded with who made it. `title_runs/gh.py` is the one interface to GitHub. It has a REST implementation,
written but not run against GitHub, and the fake.

## What it does (round 1: the tester's own poller)

1. **Poll** (`title-runs poll`). A GraphQL listing of the repository's pull requests, kept on disk
   (`state/cache/pull-requests.json`). The first poll lists the open PRs (about 17 pages and 18 points for 800 PRs);
   later polls list PRs of every state by `updatedAt`, newest first, only back to the newest one cached (one page, 2
   points). Followed PRs are also read directly every poll. No search API is used. A poll stops before the GraphQL
   budget left falls below `github.budget_reserve`.
2. **Follow** (`[follow]`): PRs listed by number; optionally every open PR whose `Unblocks:` line names one of the
   tester's title IDs, or that carries a chosen label.
3. **Debounce** (`[poll] debounce_minutes`, default 10): a new head is built only after it has been unchanged that
   long. A head replaced before it was built is marked superseded and never built.
4. **Trust** (`[trust]`): a head runs without asking when the PR's author and the head commit's author are on the
   allowlist, or the PR carries a maintainer label. Any other head pauses until the tester runs
   `title-runs confirm <PR>`; a confirmation covers that head only.
5. **Job** (`title-runs run`): fetch `refs/pull/N/merge` (GitHub's merge of the PR into its base branch) and the head;
   build the merge and main at the merge's base (its first parent) in two worktrees of the tester's clone, with build
   directories that are kept and rebuilt incrementally. A PR without a merge ref (it does not merge cleanly) is
   reported as such.
6. **Run**, per title, in the sandbox (below):
   - a title with a route (`routes/<ID>.json`): the harness's measurement protocol, main against the PR:
     warm-ups only for a build whose caches are cold, each running the route and then staying in the scene until its
     last 60 s built no pipelines (at most 20 minutes); one 60 s window from the settle points; two counted runs per
     side in the order A B A B, checked by the harness's `capture.py` (one window summary line, complete totals, no
     load frame, no pipeline build in the window, frame dumps stopped before the window), a run that does not count
     repeated once; main's `tools/performance_compare.py` per pair. The verdict rule: a difference counts when it is
     larger than both sides' spreads.
   - a title without a route: #7264's `prepare()` and `run_title()`, unchanged: boot twice (cold, then warm) for the
     title's `boot_seconds` (default: titles.json's `seconds`, else 60) and classify each run (`relink-failed`,
     `crashed`, `exited`, `stalled`, `blank`, `rendering`). `run_title()` is given a wrapper that starts the title
     in the sandbox, and an environment with only the title's variables.
7. **Report**: one Markdown comment per PR and machine: title, scene, machine (GPU, driver, OS), base, merge and head
   commits, the outcome per side, p50/p90/p99 and GPU per present with the verdict, the summary lines in a collapsed
   block, a screenshot placeholder, and a table of earlier heads. The comment is edited for each new head; a new
   comment is posted instead when an outcome changed (a side that rendered now crashes, or the reverse) or the
   verdict changed (no difference to faster or slower, or faster to slower), because edits notify nobody.
8. **Post**: dry-run by default. The body and the API call it would make go to `state/outbox/<PR>/`. The real poster
   (`poster.enabled = true` and `run --post`) edits the bot's comment by id with the token in `poster.token_env`.

## Setup

```
git clone <this repository> ~/src/anyps5-title-runs
cp config.example.toml config.toml          # edit: titles, dumps, follow list, allowlist
sudo pacman -S bubblewrap                    # or your distribution's package
gh auth login                                # for reads through the gh CLI (or set github.client = "token")
./title-runs poll                            # every few minutes, e.g. from a systemd timer
./title-runs status
./title-runs confirm 8104                    # for a paused head
./title-runs run                             # build and run the ready heads; comments go to the outbox
```

`source.repo_dir` is a clone of the repository with its submodules checked out; jobs make worktrees from it and fill
their submodules from its submodule repositories at each side's pins (nested ones included). Without a `.git` in the
worktree's `3rdparty/ffmpeg-core`, CMake needs `-DFFMPEG_PREBUILT_DIR=<an unpacked ffmpeg package for the pin>` in
`source.cmake_args`.

Per title: the dump directory (an extracted package: `eboot.bin`, `sce_sys/param.json`), optionally a route, seed
files (save data and settings copied into the title's private game directory before its first run), `app0_skip`
(package entries to leave out of `app0`), the Graphics Mode the seeded settings select (for the report) and extra
environment.

## The bot account

The poster is off until `poster.enabled = true`, and even then posts only with `run --post`. To turn it on:

- a GitHub account for the bot (GitHub's terms allow one machine account per person, run by that person);
- a token for it in the environment variable `poster.token_env`. The repository belongs to someone else, so a
  fine-grained token cannot write to it (those reach only the token owner's repositories, and other public ones
  read-only). Use either a classic token of the bot account with the `public_repo` scope, which can comment on any
  public repository and also edit or delete the bot's own comments there, or a GitHub App that the repository's
  maintainer installs, with "Pull requests: Read and write" (comments on a PR go through the issues API);
- for the poll, no write access: the `gh` CLI's login or any token, since the pull request data is public.

The poster keeps the bot's comment id in `state.json`. If that file is lost, the next post is a new comment; it
does not yet look for the bot's earlier comment by its marker.

## Routes

A route is data (JSON): pad steps and frame-state conditions to a named scene, as the harness's `nav.sh` does. Frames
come from `APS5_DUMP_FRAMES`, classified by the harness's `frame_state.py` (black, title, calibration, colour);
presses go through main's `tools/pad_input.py`; load detection reads the 10 s summaries (`steady.py`). The step
vocabulary is in `title_runs/route.py`. `routes/PPSA04263.json` is GTA V's: title, calibration, landing page, two R1
presses to the Story tab, Resume Story, then until the Story has loaded. Timed runs stop the route after the
Resume Story press (`timed_stop_after`) and wait for the window.

## The trust model

A followed PR's code runs on the tester's machine. What stands between that code and the machine:

- **The allowlist and confirmation.** Only heads by listed authors (or under a maintainer label) run unattended.
  GitHub links a commit to an account by its e-mail address, which a pusher can set to anyone's, so the head commit's
  author is a hint, not proof; the PR's author is the account that controls the head branch, but anyone with push
  access to that branch can push to it. Keep the list short.
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

Only the bot's comment: timings (frame times, GPU time per present), the summary lines AnyPS5 prints (build commit,
GPU, driver, OS, CPU core count, memory, environment switches, top phases), outcome classes, the first error line of
a title that does not render, the machine name and tester name from the config, and, when enabled, a screenshot of
the scene. Never game files, save data or the dump's contents. The poll reads public PR data from GitHub.

## Built on

- `vendor/title_run/`: #7264's `tools/title_run.py` (LeandroLP23), unchanged, at c2dce8dd3: discovery, relinking and
  layout (`prepare()`), outcome classes, `summary.json`, the generic boot-and-classify run.
- `vendor/gtav_harness/`: the harness's `frame_state.py`, `steady.py` and `capture.py`, unchanged, at ef6636d: frame
  states, load detection, the Performance report form's protocol (window, warm caches, counts / not counted, quiet).
- Main's `tools/performance_compare.py`, `tools/trace_digest.py` and `tools/pad_input.py`, from each job's checkout of
  main's base commit.

What this repository adds is listed in `SUGGESTIONS.md`, with the parts that could go back to #7264.

## Demo: a second head

`demo/simulate_head.py` copies the state (not the trees, builds or runs), writes a fixture listing in which the PR
has a new head and a results file for it (the real head's measurements, marked as simulated in the comment), and
prints the times to poll at. Then, with the copy's config:

```
./title-runs --config COPY/config.toml poll --fixture COPY/fixture-listing.json --at SEEN       # new-head, waiting
./title-runs --config COPY/config.toml poll --fixture COPY/fixture-listing.json --at SEEN+11m   # paused (not on the allowlist)
./title-runs --config COPY/config.toml confirm 8104
./title-runs --config COPY/config.toml publish 8104 --results COPY/fixture-results.json       # edit, with the earlier head in the history table
```

## Tests

```
python3 -I -m unittest discover -s tests -t tests
```

The poller against fixture listings (first and incremental polls, direct reads), the follow rules (Unblocks:, labels,
drafts, closed PRs), debounce and supersede, the allowlist and confirmations, the verdict rule, the comment's
contents, history and the edit-or-new rule, the dry-run poster, and `publish` refusing a head that is not ready.
