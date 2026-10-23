# Design: testing AnyPS5 pull requests on your own games

Status: 2026-10-23, after the queue was taken out ("Local tests alone" below). STATUS.md says where the code stands;
README.md how to use it.

## Why

AnyPS5 merges around the clock, but review and testing are the bottleneck: anything that touches rendering, memory or
the recompiler has to run on real games first, and the project's developers ask for results from hardware they don't
have (Windows, AMD and Intel especially), with the GPU, the title ID and before/after.

People with dumps and hardware can give that. This tool lets anyone test a pull request on their own games and machine,
against main, the way the project's performance reports ask, and post the report themselves.

## Principles

1. **The tester decides what runs.** Only pull requests they add, or open ones by people they follow, and of those only
   a head the pull request's own author pushed. Nobody else can make their machine run anything.
2. **Nothing is posted for them.** Each result stays on their computer with a report they may post by hand.
3. **Nothing for the project to do, nothing to sign in to.** No App to install, no repository to keep, no labels, no
   account for the tool.
4. **The project's reporting requirements come first.** A report has what the project's performance form asks for:
   the protocol (warm caches, A B A B, counted windows), the summary lines as AnyPS5 wrote them, and each trace
   attached. Where it can't (a trace over GitHub's limit), it says so.
5. **Easy and quiet.** Go through the first-run walkthrough once and leave it running. It tests when the machine is
   idle, or in the hours the tester set where idle can't be told, gets out of the way when they use it, and asks
   something only when it must.
6. **Nothing of the game leaves the machine.** Timings, summary lines and traces go out only in a report the tester
   posts.

## Pieces

- **The window and the tray** (`title_runs/ui/`, PySide6) and **the command line** (`title_runs/cli.py`), both over
  **the engine** (`engine.py`, no Qt): the testing switch, local tests, the schedule, what's shown. They can run at once
  on one state folder (`locks.py`). Linux and Windows from the start; the Windows paths are written but not run yet.
- **Local tests** (`local_tests.py`): the list, reading it from GitHub, main pinned with the fixes, a test, its result
  and its report.
- **A test** (`job.py`, `sources.py`, `build.py`, `game.py`, `protocol.py`, `route.py`, `scenarios.py`): the head merged
  onto main locally, both built in the build sandbox, then timed main against the pull request on the tester's games
  in the title sandbox (`sandbox.py`).
- **Reading GitHub** (`gh.py`, `sources.pull_heads`): without a sign-in, read only. Heads come from git; the API is
  asked only what git can't tell ("Reading GitHub without a sign-in").
- **The verdicts** (`verdict.py`) and **the listing** of the project's pull requests (`listing.py`).

## Trust and safety

- **Which heads run.** A pull request the tester added, or one opened by someone they follow; and only a head the pull
  request's own author pushed. The pusher is the actor of the pull request's first workflow run for that head; a head
  with no workflow run, or pushed by anyone else, isn't tested and the Local tests page says why. Following someone
  tests each new head they push without the tester looking at it first, and the page says so where it's set.
- **Nobody checks a change before it runs.** Choosing it is the tester's trust in its author; the walkthrough says so.
- **The sandbox** is the second line: builds without network, GPU or display; the game with the GPU and the display
  only, no network, no home directory, the dumps read-only. What it doesn't stop (a driver or kernel exploit through
  the GPU, the display, filling the disk, anything run with the sandbox off) is in the walkthrough and the README.
- **The head is built by its SHA**, merged onto main locally, never `refs/pull/N/merge` or whatever the branch points
  at later.

## Verdicts

- **Per machine**: the difference of the mean p50s (PR − main) counts only when it is larger than both sides' spreads
  (max − min of each side's p50s) *and* larger than 1 % of main's mean p50. Otherwise "no difference". A difference
  that passes one of the two tests but not the other is **borderline**.
- **Per class**, for a pull request run on several machines: machines with the same GPU model, driver branch (the
  driver's first version field: NVIDIA 615, Mesa 24.2) and OS are combined, and only with machines timed in the same
  scenario. The per-machine differences are combined, never raw frame times, since machines differ: "faster on 3 of 3
  RTX 5060 Laptop · NVIDIA 615 · Linux machines, median −0.3 ms (−0.4 %)". A class is faster or slower when a majority
  of its machines are and none goes the other way; "mixed" when both happen; otherwise no difference. A class is
  borderline when its only machine is, or when its machines disagree and fewer than three have reported.
- The 1 % and the three are `verdict.DEFAULT` (they were the results repository's settings until "Local tests alone").

## The tester's experience

### First run: the walkthrough

Nothing runs until the tester has been through it once. One page each:

1. **What this does**: they pick pull requests; this machine builds and times each against main on their own games when
   it is free, and writes a report in the project's form for them to post if they want. What leaves the machine:
   nothing by itself; a report they post says what it ran on and how fast, with the traces they attach. Never game
   files.
2. **The sandbox**: what it keeps out, and what it does not protect against, including the change itself. The tester
   ticks that they have read it.
3. **When it may run**: on idle where the machine can tell (a desktop that reports idle to logind, or Windows); where
   it cannot (Hyprland without an idle daemon never sets logind's IdleHint), the page says so and the tester sets
   hours instead. Mains power only; pause while a fullscreen program or a named program runs.
4. **Your games**: the folder the dumps are in, which have a full test and which a start-up check, and the AnyPS5 clone
   builds take main and the change from.

The last page sums it up and says to add pull requests on the Local tests page.

### The tray

```
 ● AnyPS5 title runs                        tray menu
   ─────────────────────────────────────
   Testing #4287 (a local test)
   Next: #9289 perf(agc): batch a dispatch run's staged copy-ins
   1 PR waiting for you
   ─────────────────────────────────────
   Testing: Off
 ✓ Testing: On schedule
   Testing: Now
   ─────────────────────────────────────
   Open…
   Quit
```

Dot: grey idle, green running, amber waiting for you (a pull request that mentions the tester's games and isn't on
their list), red error. The tray is optional (Settings, This app): without it, closing the window quits and stops the
test, so nothing keeps running after the app.

### The window

A sidebar with four pages:

- **Home**: what this machine is doing in one line; the testing switch, **Off · On schedule · Now**, with what the
  chosen position means; Stop this test while one runs; the steps of the running test and the game itself, shown
  inside the window; Up next; Results, each with its report.
- **Local tests**: below ("Local tests and the testing switch").
- **All pull requests** (the advanced view): the project's open pull requests in four sections (on your local tests,
  mentions your titles, labelled perf/agc/shader, everything else), each with Add to put it on the local tests list.
- **Settings**: this machine, the sandbox check, what's shared, when to test, your games and their scenarios,
  the app (text size, the simple or advanced view, the tray), and in the advanced view the logs.

## Open

- **Windows sandbox.** A restricted token or AppContainer for the run with GPU access, or a Windows Sandbox VM (vGPU
  support is limited).
- **Repeatable scenes.** Saves in missions, and input recorded from play and replayed for longer runs ("Scenarios").
- **Routes beyond GTA V.** Routes are per title; a small route recorder (press, wait for a frame state, mark) would let
  testers add their own.
- **Disk.** Two builds per test and warm caches per build; a cap with least-recently-used eviction.
- **Posting.** By hand. A narrowly scoped App that posts a report with the tester's approval for each post was
  discussed and isn't built.
- **Renting machines** (Vast) for the tester's own picks.

## Local tests and the testing switch (Charlie, 2026-10-22)

After the first night of local tests (17 upstream PRs, 2026-10-21).

1. **The testing switch** replaces Start, the automatic box and the tray's Pause: **Off** (no test starts), **On
   schedule** (tests start by themselves within When to test), **Now** (one test after another whatever the schedule
   says, until switched back). Switching doesn't end a running test; **Stop this test** does, and sets the switch to
   Off so nothing starts a minute later. A Pause from before the switch reads as Off.
2. **Local tests are a page of their own**, not a list in the config: add a PR by number or link, follow people (their
   open PRs), test again, remove (a followed person's PR then stays off). Each PR shows its newest result, and its
   earlier ones in the report window. Testing a head again keeps the earlier result (2026-10-23): each test has its own
   job folder (`<pr>-<head>-<scenario>`, then `-2`, `-3`), draft and traces, where a second test used to overwrite the
   first's results, so the first's report showed the second's numbers.
3. **Fixes on both sides.** PRs merged onto main for both sides, for a main that can't run the tester's games without
   them (main aborted GTA V at boot from fe4016f61 until #9730). A fix main already has is left out; a fix that
   doesn't merge, or whose head its author didn't push, holds local tests and says why.
4. **A main that doesn't start the game holds local tests**, until main is pinned again (12 hours, or Use the latest
   main) or the fixes change.
5. **The report is the project's own form**, as reviewers asked for it on #4287 and #7516: what ran where, main against
   main + the PR in A B A B order, p50, GPU busy and p99 per run, what wasn't tested, and the summary lines as AnyPS5
   wrote them. Nothing mentions anyone.
6. **Posting is the tester's, by hand.** The report window gives the PR's link first, the text (editable) with Copy,
   and **Mark as posted**. Nothing in the client posts a local result. A result not posted goes **stale** when the PR
   gets a newer head, closes or merges, or after 48 hours (main has moved on); a posted one never does.

## Scenarios (2026-10-22)

Charlie chose saves as the next feature: runs the tool can time without anyone playing, from save files found online,
GTA V first. A **scenario** is one specific run of a title, which may or may not load a save: how to get there, what is
on screen, and what keeps it the same. GTA V's prologue is one (no save: with no story save, Resume Story starts a new
game); Franklin's front door is another (a 100% save).

What the first boots showed (main c49fa17ee, this laptop, 2026-10-22):

- **A PS4 save loads in the PS5 game.** Apollo's PS4 "100% Save Game" is GTA V's save-data memory, `memory.dat` (1 MiB,
  "(Autosave) A Starlet In Vinewood (100.0%)"). Copied in as AnyPS5's save-data memory slot 0
  (`_sd_mem/u268435456/slot0.bin`), Resume Story loads it: Franklin at the front door of his Vinewood Hills house, in 80 s.
  With save-data tracing the PS5 game also looks for PS4's save folders by name (`SAVEDATASGTA50000` to `14`,
  `SAVEDATAPROFILE`, `SAVEDATAMISREP0000`).
- **The idle camera.** With no input GTA V starts its idle camera after about 30 s and turns it differently on every
  boot: the house gave 64 to 119 ms frames by 10 s interval, where the prologue (a mission, no idle camera) holds 78 to
  81 ms. D-pad left every 10 s (nothing on foot there) kept the view still for 150 s and the frames at 85.9 to 89.5 ms.
- **The camera's framing at the load is GTA V's own, and differs from boot to boot.** 11 boots of the same save gave
  five framings; each boot keeps its own. The first A/B in the house (#4287) had main at 86.8 and 92.0 ms, where the
  prologue's spread on the same builds is 0.1 ms. Tried and not working: cycling the camera modes with the touchpad (it
  lands on a different mode each boot), walking forward (Franklin sometimes walks out of the front door), and pressing
  the touchpad until the frame looks like first person (first person is not the same picture on two boots either, 0.55
  alike, and neither a picture nor colours tell first person from the other modes reliably).

How it works (scenarios.py):

1. **A scenario is a file**, `scenarios/<TITLE ID>/<id>.json`: its name, the report's words for what is on screen, the
   route that gets there, the save and where it goes (optional), the still button (optional), and the scene's colours.
   One of a title's scenarios is its default (GTA V's: the prologue).
2. **The save is never stored here.** It is downloaded once from its source, pinned to a commit, checked against its
   sha256 (and the zip member's), and kept under the state directory; a save's licence is its source's (Apollo's
   saves are GPL-3.0, this tool GPL-2.0). Save-data memory slots only, for now; save folders (`_sd/<name>/`) when a
   scenario needs one.
3. **A title runs in one scenario** (config `scenario = "<id>"`, or the Titles page's Scenario), its default when none
   is named. A job downloads and checks the save before it builds anything.
4. **A scenario's runs are its own**: `runs/<TITLE ID>-<scenario id>`, so a warm-up in the prologue never counts as warm
   for the house, and the window comes from the house's own settle point. The job folder carries the scenario's id too,
   so a head tested in two scenarios keeps both results.
5. **The still button** is pressed every few seconds from Resume Story until the run stops, in warm-ups and timed runs
   alike, and the report says so ("with D-pad left pressed every 10 s ... and no other input").
6. **Each run is checked to be in the scene**, by its colours (frame_state's 96x54 sample in 4x4x4 colour boxes) against
   the scenario's, and a black frame never is. A save the game didn't load starts the prologue instead, and a story save
   in the seed would load instead of the prologue. The house's runs were 0.07 to 0.17 from its colours, the prologue's
   own runs 0.25 at most from theirs (the mission's camera cuts), and the two scenes 0.41 to 0.50 apart; the house allows
   0.3, the prologue 0.33. A warm-up that isn't in the scene fails its route; a timed run that isn't does not count.
7. **Results carry the scenario**: the report names the save (source, file, sha256, where it went) so anyone can load
   the same one, and machines are combined only with machines timed in the same scenario.

The camera in the house, from Charlie (2026-10-23): don't fight the framing at the load. Play for longer instead (walk
out of the house and on), so more of each run is the same than differs; that needs input recorded from his play and
replayed. Saves in missions are the better way to repeatable tests, and open-world play has to work too.

## Reports with their traces (2026-10-23)

The project's performance form requires each trace attached (Traces: "Attach each aps5-trace-<commit>-<pid>.json.gz"),
asks for its digest (`tools/trace_digest.py`), and has the summary lines; its capture rules are warm caches, no other
`APS5_TRACE_*` or `APS5_PROFILE_*` switch, and the log not redirected. GitHub takes attached files other than images and
videos up to 25 MB, and comments up to 65,536 characters. Our reports had the summary lines only, and every trace so far
was over the limit: 700 presents of the prologue made 32 to 36 MB.

What a trace's size follows (the 100 traces of 2026-10-21 and 22, this laptop): one slice per draw stage, about 4,400
events per present in the prologue, 74 % of the bytes on the queue worker and 24 % on the draw committer. The prologue
was 46 to 52 kB per present, the house 47 to 60 (where the camera looked further). None of that can be cut without
another switch, so the window is what changes.

1. **The window**: 60 s, or as many presents as fit a 20 MB trace at the most bytes per present of the scenario's last
   eight timed traces on this machine (both sides of its last two tests), whichever is fewer (`protocol.trace_presents`),
   in tens and at least 100. The last eight, not all, because a trace's size follows main too: the prologue was 46 to
   52 kB per present on the mains of 2026-10-21 and 22, and 40 to 41.5 on 15e71dbe1. Without an earlier trace it takes
   61 kB per present (GTA V's heaviest so far): 320 presents. The 5 MB left under the limit is for a stretch heavier
   than any seen; the house's heaviest trace was a quarter above its other three. Each timed run's meta says how its
   window was sized.
2. **What a shorter window costs**, from the first N presents of the 20 complete prologue A/Bs (same start, p50 of the
   present intervals, the verdict rule as it is): the larger side's spread, median 0.30 ms at 700 presents, 0.35 at 400,
   0.40 at 350, 0.50 at 300, 0.70 at 250; no verdict changed at any of them. 1 % of main is 0.78 ms there.
3. **The report** has, after the summary lines, a Traces line with room under it for the files, and each trace's digest
   folded (`<details>`), in the order of the summary lines. A trace over 25 MB is named as not attached, with its
   size. When the digests would take the report over 65,536 characters they are left out, and the report says so.
4. **The names.** In the sandbox the game is the same process ID in every run, so a side's two traces have the same
   name (`aps5-trace-c49fa17ee046-3.json.gz` twice). The files to attach are AnyPS5's names with the title and the run
   added: `aps5-trace-c49fa17ee046-3-PPSA04263-main-1.json.gz`, and `-pr-1` for the runs with the PR. They are hard
   links in `local-tests/attach/<job>/`, so they take no more space.
5. **The report window** lists the traces under Traces to attach, all selected, so one drag from the app takes them all
   into the comment; Open the folder opens them in the file manager. A trace over the limit is listed with its size,
   can't be dragged, and the window says the report doesn't have what the project's form asks for, and to test it again.
   The drag from the app (an X11 window) into Chrome (also X11 here) is untested.
6. **The first test with it** (2026-10-23, #4287 at 7aea3fe29 against main 15e71dbe1, which has #9730, through
   `LocalTests.run` with the app closed): the prologue's first test in its own runs folder, so 320 presents (24 to
   25 s). Traces of 12.7 to 13.3 MB; main 75.9 and 75.4 ms, with #4287 70.7 and 70.4 ms, faster by 5.11 ms (6.8 %), as
   on 2026-10-22 with 700 presents on main 4777caca3 + #9730 (79.1, 79.0 against 73.8, 74.0). The report is 25,592
   characters with its four digests. The next prologue test gets 480 presents.

## Local tests alone (Charlie, 2026-10-23)

Charlie decided to take the queue out: the results repository and its relay workflow, registering machines, the App
queueing and commenting on pull requests, and testers' machines running what a maintainer queued. Why:

- **Safety.** Nothing makes someone's machine run code they didn't pick: whoever runs a test chose it.
- **Nothing for maintainers to do.** No App to install, no repository to keep, no labels. They get reports in the
  form they already ask for, posted by the person who ran the test.
- **Local tests are what proved useful**: the 17 pull requests tested overnight on 2026-10-21 and #4287's -5.11 ms
  on 2026-10-23 were all local tests.
- **The queue had no safe way to run on time.** GitHub's schedule ran the relay 11 times from 21 to 23 October, 2 to
  6 hours apart. It only kept up while the window started it with `gh workflow run` (removed in 407710f); every other
  way needed something hosted, a workflow in AnyPS5, or runs started from testers' accounts.

Kept:

- local tests: pull requests by number or link, following people, fixes on both sides, testing again, the reports
  with their traces, posting by hand and stale results. Following someone is the one way a test runs a head the
  tester hasn't looked at, so it says so where it's set;
- signing in through the App, as a sign-in only: the tool reads the project's pull requests with it (GitHub allows
  60 requests an hour without one), and the App needs no permissions for that;
- the verdicts: per machine, and combined over machines of one class, for a pull request run on several machines of
  the tester's own;
- the window, the command line, scenarios and the sandbox.

Next, later: renting machines (Vast) to run the tester's own picks on, so the trust stays the tester's.

On GitHub, Charlie retires the results repository (CPritch/anyps5-title-runs-results) and cuts the App back to a
sign-in. The queue's design and code are in git history: DESIGN.md and FORMATS.md as they were at 407710f. This
also ends "Local tests only" (2026-10-23), a config with no results repository: every config is that now, with the
App to sign in with under `[github] app`.

## The command line (2026-10-23)

For people and for agents driving the tool (a tester's agent running local tests and fetching their reports). The
first round's poller and bot poster went with it: nothing in the tool posts a result, and nothing uses the gh command
line.

1. **One table** (`cli.COMMANDS`): each command's group, summary, description, what it changes, its JSON and examples.
   The parser, `title-runs help`, each command's `--help` and docs/CLI.md are made from it, and a test checks
   docs/CLI.md matches, so the help can't drift from the commands. Commands are words a person would use: `status`,
   `testing now`, `local add 4287`, `local report 4287`, `run --once`, `stop`.
2. **What it changes**, in every command's help ("Changes: ..."): at most this computer's settings and lists. No
   command writes to GitHub (the queue's did, until "Local tests alone").
3. **For scripts and agents**: `--json` on every command (one object; one per line for `run`, which goes on for a
   while), exit codes 0 (done), 1 (couldn't, with why) and 2 (written wrong), no prompts.
4. **The same engine as the window.** The window's logic moved to `engine.py`, which has no Qt; the window
   (`ui/app.py`) adds only opening links through the desktop. The command line works without PySide6, but `window`.
5. **The window and the command line at once**, on one state folder and one config (`locks.py`):
   - the status file, the local tests list and the config are each changed under a file lock;
   - one test runs on a computer at a time (the runner lock, which names the process holding it); a process that
     isn't testing leaves the status file to the one that is;
   - a stop asked for in either (Stop in the window, `title-runs stop`) ends the test where it runs: the holder of the
     runner lock watches the status file for it;
   - a setting changed on the command line reaches the open window within two seconds, and a save by the window keeps
     it: the window takes the settings changed on disk since it last read or wrote the file, except those it changed
     itself.

## Reading GitHub without a sign-in (Charlie, 2026-10-23)

After "Local tests alone" the App's only job was reading: GitHub allows 60 API requests an hour per IP address without
a sign-in (5,000 with one), and its GraphQL API, which All pull requests used, refuses anonymous calls. Charlie decided
to drop the App and read without a sign-in:

1. **Heads come from git.** `git ls-remote <project> 'refs/pull/*/head'` returns every pull request's head in one
   call (8,822 of AnyPS5's in 0.3 s on 2026-10-23), and git isn't counted against the API's limit.
2. **The API is asked only what git can't tell**: a pull request's title, author and state when its head is new to the
   list, and every 6 hours whether it closed or merged; who pushed a new head (its first workflow run); and for each
   person followed, their open pull requests (the search API, which has its own limit, 10 a minute without a sign-in).
3. **All pull requests** reads the project's open pull requests with the REST API, 100 to a request (14 requests for
   AnyPS5's 1,314 open ones on 2026-10-23), only when the tester presses Refresh.
4. **When the limit is used up**, nothing more is read until GitHub's reset time, and Home says until when.
5. **What goes**: the App, the sign-in and its token on disk (a token kept from before is deleted), the walkthrough's
   sign-in page, `title-runs sign-in` and `sign-out`, and `[github] app`. Charlie can delete the App, title-runs-dev.

## Recorded play (Charlie, 2026-10-23)

Charlie's idea for scenes that differ less from run to run: a "record a scenario" step where he plays (input locked
out for the first second), the tool records the controller, and runs play the recording back. What AnyPS5 and this
tool already do decided how:

- **Runs never see a real controller.** They set `APS5_NO_PAD_INPUT=1` and hide every controller from SDL; input
  comes only from the pad command file (`APS5_PAD_INPUT_FILE`), as the routes' presses do. So recording passes the
  controller through that same file while it records, and playback writes the same commands: the game gets input the
  same way in both.
- **The pad file.** AnyPS5 (15e71dbe1, `InputCommandFile.hpp`) reads it at most every 100 ms of its process time, when
  the game reads the pad. A command is a sequence number, buttons, a hold of up to 5 s, and optionally both sticks.
  Its timeline form (`APS5_PAD_TIMELINE`) is exact to the millisecond but has buttons only, and walking needs the
  sticks. So the tool writes a command every 50 ms with a 250 ms hold (input stops by itself if the tool does), and
  the game takes the latest one each time it reads the file.
- **The controller** is read from Linux's evdev with the standard library: systemd gives joystick devices to the
  logged-in user (`70-uaccess.rules`), so no root is needed. Buttons follow the Linux gamepad layout (south is Cross);
  Select (Create, or Xbox's View) is the touchpad; triggers count as L2 and R2 past a third of their travel.
- **Playback is by time, not by frames.** In a timed run there is no live frame count to follow: frame dumps must stop
  before the window (the project's capture rules), and the window's summary comes only at its end. Time is also what
  GTA V's world moves by. Both recording and playback start at the same point: the first frame dumped after Resume
  Story that is in the starting scenario's scene (its colours), so a slower load doesn't shift the input.
- **A recorded scenario** is the starting scenario (its route, save and start colours) plus the track: the state at
  each change, in milliseconds from that start. The window opens about 30 s after the scene loads and lasts up to 60 s,
  so a recording is at least 100 s. After the track ends, the starting scenario's still button carries on. A run whose
  scene never showed, so the track never started, doesn't count. Recorded scenarios are kept in the state folder
  (`scenarios/<TITLE ID>/<id>.json`), next to the tool's own.

The first test (2026-10-23, main 15e71dbe1, Franklin's front door, a scripted controller in place of a real one: walk
5 s, look right 2 s, walk 6 s, then nothing until 100 s):

- **The input reaches the game.** Stick commands through the pad file walked Franklin out of his front door to his car.
- **Playback follows the recording**, with two differences. The camera's framing at the load is GTA V's own each time
  (known from the house), so the same walk is seen from a little further back or closer. And the recording session's
  cache was cold where the walk went: a 16 s stall while it built pipelines swallowed part of the walk, where the
  playback, warmer, stalled less and went further (by 19 s, Franklin was beside the car rather than at the door). So a
  recording is best made with the cache already warm along the way: the same walk once before the one kept.
- **GTA V asks about its autosave.** About 25 s after walking out, both runs stopped at an Alert, "The autosave slot
  already contains '(Autosave) A Starlet In Vinewood (100.0%)' ... overwrite", and stayed there. Standing at the door
  (the house scenario's runs) never brought it up. A player answers it, but a recorded answer only lands if it comes at
  the same moment; turning autosave off in the game's settings (they are in the profile save the title's seed copies
  in) keeps it from asking.
