# anyps5-title-runs

Test AnyPS5 pull requests on your own games and hardware. You choose the pull requests. Each new commit is built, run
in a sandbox on a game you own, and timed against AnyPS5's main branch the way the project's performance reports ask.
The result stays on your computer with a report in the project's format, which you can post yourself. Nothing is
posted for you, and AnyPS5's maintainers don't have to set anything up.

Python 3.11 or later, the standard library only; the window needs PySide6. Linux, with bubblewrap for the sandbox; the
Windows paths are written but not run yet.

DESIGN.md says what the tool is for and why it is as it is, and docs/CLI.md has every command.

## Getting started

```
git clone https://github.com/CPritch/anyps5-title-runs ~/src/anyps5-title-runs
sudo pacman -S bubblewrap                    # or your distribution's package; and PySide6 for the window
~/src/anyps5-title-runs/title-runs window    # a new config: the first-run walkthrough sets it up
```

The walkthrough explains what the tool does and what leaves your computer, what the sandbox does and doesn't protect
against, and when tests can run (when you're away, if the computer can tell, otherwise in hours you choose; only when
plugged in; paused while something is fullscreen). It then finds your games and your copy of AnyPS5's source. Nothing
runs until you've finished it. After that, add the pull requests you want tested on the Local tests page, or with
`title-runs local add`.

There's nothing to sign in to. The tool reads GitHub without an account: the latest commit of every pull request comes
from git, and GitHub's API is only asked for what git can't tell it, within the 60 requests an hour GitHub allows
without a sign-in. The All pull requests page only loads when you press Refresh. If the hourly limit is used up, Home
says when it resets.

## The command line

`title-runs` does what the window does, from the same config and state folder, with the window open or without it:

```
title-runs status                    what this computer is doing, and anything to fix
title-runs testing now               the testing switch: off, schedule or now
title-runs local add 4287            a pull request for your local tests
title-runs run --once                one test now, ignoring the switch
title-runs local report 4287         its report: the link to post it on first, then the text
title-runs local files 4287          the traces to drag into the comment
title-runs local posted 4287         record that you posted it
title-runs help local report         what a command does, what it changes, its JSON and examples
```

For agents and scripts: every command takes `--json` (one object; one per line for `run`), and exits 0 when done, 1
when it couldn't (the message says why) and 2 when it was written wrong. No command posts anything or writes to
GitHub. A setting changed on the command line reaches an open window within a few seconds, one test runs on a computer
at a time, and `title-runs stop` ends a test the window started. docs/CLI.md has every command, made from the commands
themselves.

## The window

- **Home**: the testing switch (Off, On schedule, Now), the test running with its step and the game itself inside the
  window, what's next, and the results.
- **Local tests**: add a pull request by number or link, follow people, test again, choose fixes to include, and see
  which version of main they're tested against. Each result has a report window with the link to post it on, the text
  to copy, the traces to drag into the comment, and Mark as posted.
- **Games**: your games, each with its test and the scenario it's tested in; Add a game…, Remove, Record a scenario…,
  and your recorded scenarios, which you can delete.
- **All pull requests** (the advanced view): the project's open pull requests (those on your list, those that mention
  your games, those labelled perf, agc or shader, then the rest), each with Add to put it on your local tests.
- **Settings**: this machine, the sandbox check, what's shared, when to test, the app's look, and the logs.

Closing the window quits and ends a running test, unless it is set to keep running in the tray.

## Local tests

Each commit a pull request's author pushes is tested once. Following someone tests all their open pull requests the
same way, including every new commit, without you checking it first. Main stays at one version for 12 hours, so the
pull requests tested together are compared with the same main, which is built and warmed up once. Fixes (pull requests
main needs before it can run your games) are merged into both builds. The report follows the project's format: what
ran where, main against main plus the pull request in the order A B A B, the summary lines, one trace per run under
GitHub's 25 MB limit, and each trace's digest. You decide whether to post it. A result you haven't posted is marked out
of date when the pull request gets new commits, closes or merges, or after 48 hours. Testing a commit again keeps the
earlier result. DESIGN.md has the details ("Local tests and the testing switch", "Reports with their traces").

## What a test does

A test is one commit of a pull request on your local tests:

1. **Job**: fetch the commit by its SHA and the version of main being tested against, with the fixes merged into it,
   and merge the commit onto that main locally (with a fixed identity and the commit's own date, so every machine makes
   the same merge). Both sides are built in two worktrees of the tester's clone, with build directories that are kept
   and rebuilt incrementally. A commit that doesn't merge is reported as such.
2. **Run**, per title, in the sandbox (below):
   - a title with a route (`routes/<ID>.json`): the harness's measurement protocol, main against the PR:
     warm-ups only for a build whose caches are cold, each running the route and then staying in the scene until its
     last 60 s built no pipelines (at most 20 minutes); one window from the settle points, 60 s or as many presents
     as fit a 20 MB trace (GitHub takes attached files up to 25 MB, and the project's form asks for each trace); two
     counted runs per side in the order A B A B, checked by the harness's `capture.py` (one window summary line,
     complete totals, no load frame, no pipeline build in the window, frame dumps stopped before the window), a run
     that does not count repeated once; main's `tools/performance_compare.py` per pair. The verdict
     (`title_runs/verdict.py`): a difference counts when it is larger than both sides' spreads and 1 % of main's p50.
   - a title without a route: #7264's `prepare()` and `run_title()`, unchanged: boot twice (cold, then warm) for the
     title's `boot_seconds` (default: titles.json's `seconds`, else 60) and classify each run (`relink-failed`,
     `crashed`, `exited`, `stalled`, `blank`, `rendering`). `run_title()` is given a wrapper that starts the title
     in the sandbox, and an environment with only the title's variables.
3. **Result**: the report, in the project's own form with its traces, stays on this computer; the tester posts it
   themselves, or not.

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
which each run is checked against. A title runs in one scenario (`scenario = "<id>"` in its section, or the Games
page), its default when none is named. GTA V's are `prologue` (the default: a new game, no save) and `franklins-house`
(Franklin at his front door in Vinewood Hills, from Apollo's PS4 100% save).

### Recording a scenario

A scenario can include input recorded from a controller, so each run plays through the same part of the game instead
of standing in one place. Use **Record a scenario…** on the Games page, or:

```
title-runs games record PPSA04263 --from franklins-house --name "Out of the house" --scene "Franklin walks to the road"
title-runs games scenario PPSA04263 out-of-the-house       # tests of GTA V then run in it
```

The game starts on the main build (a local test builds it) in the scenario you start from, and goes to its starting
scene on its own. If that scenario sets the camera first (Franklin's front door does), keep your hands off for those
few seconds. Then you take over. The first second is ignored, and after that everything you do on the controller goes
to the game and is recorded, for 100 to 600 s (timing starts about 30 s in and lasts up to 60). Stop ends the
recording without saving it. Every test in the new scenario sets the camera the same way and replays the recording
from there, each input on the same pad read of the game's as when you recorded it. A run where the scene never appears
doesn't count. Recorded scenarios are kept in the state folder,
`scenarios/<TITLE ID>/<id>.json`, and can be copied into this repository's `scenarios/` to share them.

The controller is read through Linux's evdev, which systemd lets the logged-in user read; `title-runs check` shows
which controller it finds. Any controller with the standard Linux gamepad layout works, and its Select button (Create,
or the Xbox View button) acts as the touchpad. DESIGN.md ("Recorded play") explains why it works this way.

## The trust model

A pull request's code runs on the tester's machine. What stands between that code and the machine:

- **Which commits run.** Only pull requests the tester added, or that were opened by people they follow, and of those
  only commits the pull request's author pushed (GitHub's first workflow run for a commit names who pushed it). Nobody
  reviews a change before it runs, so choosing it means trusting its author.
- **The build runs in the build sandbox**: the same bubblewrap setup without the GPU, the display or the network. The
  source tree, its git directory and prebuilt dependencies are read-only, and only the build directory is writable.
  The commit, main and submodule pins are fetched before the build, outside the sandbox. A malicious pull request
  still runs code at build time, but only inside the sandbox.
- **The title runs in bubblewrap:** `/usr`, `/etc`, `/sys` read-only; an empty `/home`, `/tmp` and `/run`; its own PID
  and IPC namespaces (the host's processes are not visible in its `/proc`); a new session, so it can't type into the
  terminal that started it; a minimal `/dev` with only the GPU nodes Vulkan needs (the render nodes, and on NVIDIA
  `nvidia0`, `nvidiactl` and `nvidia-modeset`; not the card nodes that set display modes, or CUDA's); one display socket,
  Wayland's when the game shows on Wayland (so it can't reach other X11 windows), X11's when the window shows it; nothing
  else of the session (no D-Bus, no audio server, no SSH agent); no network (its own network namespace). The dump,
  `app0` (hard links to the dump's files) and `libs` are read-only; only the title's game directory, its caches and
  the run directory are writable.
- **A seccomp filter**, in builds and runs alike (x86_64): the system calls that kernel escapes go through and a game
  has no use for are refused (new namespaces, ptrace, bpf, io_uring, perf events, keyrings, mounts, kernel modules and
  more; `title_runs/sandbox.py` lists them), and 32-bit system calls end the process. `title-runs check` tests it.

What this does not protect against:

- a driver or kernel exploit: the GPU's device nodes and the display server are reachable from inside, so a bug in
  the GPU driver, the kernel or the compositor can be used to leave the sandbox;
- the display: a title can draw on the tester's screen and read what the compositor lets any client read;
- resource exhaustion: no CPU, memory or disk limits are set beyond the core-dump limit;
- `sandbox.mode = "none"`, which the tester can set explicitly; every report then says the sandbox was off.

## What leaves the machine

Nothing, unless the tester posts a report. Pull requests are read from GitHub without a sign-in. A posted report has
timings (frame times, GPU time per present), the summary lines AnyPS5 prints (build commit, GPU, driver, OS, CPU,
memory, environment switches, top phases), and any traces and digests the tester attaches. Game files, save data and
the dump's contents are never included.

## Built on

- `vendor/title_run/`: #7264's `tools/title_run.py` (LeandroLP23), unchanged, at c2dce8dd3: discovery, relinking and
  layout (`prepare()`), outcome classes, `summary.json`, the generic boot-and-classify run.
- `vendor/gtav_harness/`: the harness's `frame_state.py`, `steady.py` and `capture.py`, unchanged, at ab8b91c: frame
  states, load detection, the Performance report form's protocol (window, warm caches, counts / not counted, quiet).
- Main's `tools/performance_compare.py`, `tools/trace_digest.py` and `tools/pad_input.py`, from each job's checkout of
  main's base commit.

What this repository adds is listed in `SUGGESTIONS.md`, with the parts that could go back to #7264.

## Tests

```
python3 -I -m unittest discover -s tests -t tests
```

Local tests and their reports, reading GitHub, source trees, scenarios, the verdict rules, the timed window, the
sandboxes, the command line, two processes on one state folder, and the window's model and pages (offscreen).

## License

GNU General Public License version 2 only, the same as AnyPS5 (`LICENSE` is AnyPS5's). `vendor/title_run/` is
#7264's code from AnyPS5 under that licence; `vendor/gtav_harness/` is from CPritch/gtav-harness, included under it
too.
