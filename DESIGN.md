# Design: title runs for AnyPS5 pull requests

Status: draft for Charlie's review, 2026-10-21, revised after round 2 (Charlie's four decisions, "Round 3 decisions"
below). It describes the tool we are aiming for; STATUS.md says where the code stands.

## Why

AnyPS5's maintainers merge around the clock, but review and testing are the bottleneck: anything that touches
rendering, memory or the recompiler has to run on real games first, and they have Linux/NVIDIA machines. What they
ask for (oneandonlydean, 2026-10-20) is results from other hardware: Windows, AMD and Intel especially, with the GPU,
the title ID and before/after.

Volunteers own dumps and hardware the maintainers do not. This tool lets a maintainer queue a PR for testing and have
volunteer machines pick it up, build it, run it on their own titles and report back on the PR, without the
maintainer owning a game or a machine, and without the volunteer handing anyone access to theirs.

## Principles

1. **Maintainers decide what is tested.** The trusted path is a maintainer's queue. A tester can step outside it, but
   only knowingly, and the report says so.
2. **Testers never hold a key to the repository.** They sign in with their own GitHub account through the maintainers'
   App and report as comments; the maintainers' workflow checks every report before the App posts anything.
3. **Easy and quiet.** Install, go through the first-run walkthrough once, leave it running. It works when the machine
   is idle (or in the hours the tester set, where idle cannot be told), gets out of the way when they use it, and asks
   something only when it must.
6. **Light to adopt.** A maintainer installs one App and has one public repository: nothing to host, no webhook
   receiver, no paid plan, no token to make per tester.
4. **Honest results.** The upstream Performance report protocol (warm caches, A B A B, counted windows, summary
   lines). A run that does not count says why.
5. **Nothing of the game leaves the machine.** Timings, summary lines, outcome classes, and a screenshot only if the
   tester enables it.

## Roles

| role | who | does |
|---|---|---|
| Maintainer | oneandonlydean, adriadam10 | owns the App and the results repository; queues PRs with priorities, titles and hardware |
| Tester | volunteers with dumps and hardware | runs the client; follows the maintainers' queue; may opt into unchecked PRs |
| Author | anyone with a PR | gets results on the PR; cannot queue their own PR |

## Pieces

```
 GitHub: boykopovar/AnyPS5                 GitHub: the results repository (public)          tester's machine
 ─────────────────────────                 ───────────────────────────────────────          ────────────────
 PR #8104                                  workflow "relay", every 5 minutes, as the App     client (tray + window)
  label title-test ──── polled ──────────▶   queue.json, registry.json, results/  ─ git ──▶  reads them (public)
  /title-test ... ────── polled ─────────▶   issue "Job 8104-69ac2e155ad0"  ◀── comments ── claims, results
  the App's comment ◀────────────────────    issue "Machine CPritch/laptop" ◀── issue ────── registers itself
  label removed when a push expires it       issue "Overview" (maintainers)                  (signed in with the App)
```

- **The App** (owned by a maintainer; first `title-runs-dev` on Charlie's account against his fork). Installed on
  AnyPS5 and on the results repository. No webhook (it is left inactive), device flow enabled.
  - On AnyPS5: Pull requests read and write, Issues read and write (comments, labels and reactions go through the
    issues API), Metadata read (the collaborator check). Nothing on contents.
  - On the results repository: Issues read and write, so testers' comments and issues, made with their own sign-in
    through the App, can be written there.
- **The results repository** (public, maintainer-owned). One workflow, `relay`, on a schedule (every 5 minutes) and on
  demand. It reads AnyPS5's label events, comments and new heads with the App's installation token, reads the
  repository's own issues, and writes `queue.json`, `registry.json`, `claims.json`, `results/` and the comment state
  back with the workflow's own token. Its one secret is the App's private key; the App's ID and client ID are in
  `config.json`, which is public. Public repositories run GitHub-hosted Actions for free.
- **Issues in the results repository** carry everything from testers:
  - one issue per queued job, opened by the workflow: testers claim it and report on it in comments;
  - one issue per machine, opened by the tester's client: the registration; a maintainer approves it by adding the
    label `approved`;
  - one overview issue, kept up to date by the workflow, for the maintainers.
  The workflow accepts a comment only from a registered machine's tester, and a result only with that tester's
  earlier, unexpired claim for the same head. Anyone can comment on a public issue; nobody else's comments count.
- **Testers** sign in through the App's device flow (a code they type at github.com/login/device). Their token can do
  only what both they and the App can do: in practice, comment and open issues in the results repository and read
  public data. They never get write access to the repository.
- **The client** (each tester's machine): Python, PySide6 for the tray and the window, the engine underneath.
  Linux and Windows from the start.

## The maintainer's controls

From GitHub only; no new tool to learn.

- **Label `title-test`**: queue at normal priority, any title, any hardware, two machines.
- **Comment command** (maintainers only), for detail:

  ```
  /title-test high titles=PPSA04263,PPSA01325 hw=amd,intel,windows machines=3
  /title-test low
  /title-test stop
  ```

  - priority: `high`, `normal`, `low`;
  - `titles=`: specific title IDs, or omitted for any title the tester has;
  - `hw=`: wanted hardware classes: vendor (`amd`, `intel`, `nvidia`), OS (`windows`, `linux`), or a GPU family;
  - `machines=`: how many distinct machines should report;
  - `stop`: take the PR off the queue.
- The App answers a command with a reaction (👍 accepted, 😕 not a maintainer or not understood) and keeps the PR's
  coverage table up to date.
- **Approve a machine**: add the label `approved` to its registration issue in the results repository (only people
  with triage access can add labels), or press Approve in the client's Overview tab, which does the same. `declined`
  turns it down.
- **The overview** (the pinned "Overview" issue, and the client's Overview tab): the queue with each entry's approved
  SHA and who approved it; per PR, which hardware classes and titles have reported and which are still wanted, with
  the combined verdicts; the registered machines and when each last reported; pending registrations; approvals that a
  push expired.
- Everything reaches the results repository within one scheduled run (5 minutes, sometimes longer under GitHub's
  load), so a label shows up as "Queued <sha>" a few minutes after it is applied.

## How work is spread (scheduling)

Each queue entry: PR, head it applies to (the latest unless pinned), priority, titles, hardware, machines wanted.

Each client picks its next job by a score, not first come first served:

```
score = priority weight                       (high 4, normal 2, low 1)
      × hardware match                         (1 if this machine is in hw=, 0.5 if hw= is empty, 0 if excluded)
      × title match                            (1 if it has a wanted title, 0 if titles= names none it has)
      × coverage gap                           (1 if no machine of this class has reported this head, 0.2 if one has,
                                                0 if machines= is already met)
      × age                                    (grows slowly the longer the entry waits)
```

- **Claims and leases.** Before building, the client comments a claim on the job's issue with an expiry (default 3
  hours) and reads the issue again; if another machine of its class claimed first, it withdraws (deletes its comment).
  The workflow ignores expired claims. Two testers of the same class do not run the same head at once.
- **More machines when a result is borderline.** The coverage gap is 1 again for a machine of a class whose combined
  verdict is borderline (below), until three machines of that class have reported.
- **New heads.** A new head of a queued PR supersedes the old one; a running job for the old head finishes its
  current run and stops.

## Verdicts

- **Per machine**: the difference of the mean p50s (PR − main) counts only when it is larger than both sides' spreads
  (max − min of each side's p50s) *and* larger than 1 % of main's mean p50. Otherwise "no difference". A difference
  that passes one of the two tests but not the other is **borderline**. The 1 % is `verdicts.threshold_pct` in the
  results repository's config.json (default 1).
- **Per class**: machines with the same GPU model, driver branch (the driver's first version field: NVIDIA 615, Mesa
  24.2) and OS are combined. The per-machine differences are combined, never raw frame times, since machines differ:
  "faster on 3 of 3 RTX 5060 Laptop · NVIDIA 615 · Linux machines, median −0.3 ms (−0.4 %)". A class is faster or
  slower when a majority of its machines are and none goes the other way; "mixed" when both happen; otherwise no
  difference. A class is borderline when its only machine is, or when its machines disagree and fewer than three
  have reported (`verdicts.class_max`, default 3); the scheduler then asks for another machine of it.
- The workflow recomputes every verdict from the p50 lists in the result; a tester's own verdict text is not used.

## Trust and safety

### Approval is per commit, not per PR

A maintainer approves code they have looked at, so the approval names a commit:

- **The queue pins a head SHA.** A polled label event carries no SHA, so the workflow takes the PR's head when it
  sees the label and checks that it was pushed before the label: AnyPS5's own workflow runs for that head (the PR
  checks every push starts) give its push time and pusher. If the head arrived after the label, nothing is queued.
  A head with no workflow run is not approved by a label either: nothing else says when it was pushed (a commit's
  date is whatever its author wrote), so it needs `/title-test sha=<sha>`. In both cases the App removes the label and
  posts a new comment saying why and what to do. Testers fetch the pinned commit by SHA and merge it onto current main
  locally; they never build `refs/pull/N/merge` or the branch's current head.
- **The App echoes it**: "Queued 8d4f486 for title runs". `/title-test sha=8d4f486` pins it explicitly, which closes the
  race of a push landing just before the maintainer labels.
- **A push after approval expires the approval.** The App removes `title-test` from the PR (the PR's timeline shows
  it) and posts a new comment, since the maintainer has to act and edits notify nobody: "Approval of 69ac2e1
  expired: 8118a04 was pushed after it by @someuser and is not checked. Label the PR again to queue it." Once a new
  head is queued, the notice leaves the top of the comment and stays in its earlier-heads history. Running jobs for
  the old SHA end after their current run; nobody starts a new one. A tester can still opt in to the new head
  through the trust dialog. A push with no workflow run has no known pusher, so only the same patch-ids carry the
  approval over it; otherwise it expires.
- **Carried over without a maintainer** only when nothing the maintainer looked at changed:
  - a rebase whose own diff is identical to the approved one (same patch-id per commit, or an empty `git range-diff`
    apart from the base);
  - commits pushed by an account that is a collaborator on AnyPS5 with write access (people the maintainers already
    trust with the repository), not by the PR's author. The pusher is the actor of the workflow run the push started.
- **The client checks again** just before it builds: the SHA it is about to build must equal the queue entry's, or
  the job stops.

### Paths

- **Maintainer-queued**: runs per the tester's schedule without asking.
- **Not checked** (a PR no maintainer has queued): the tester can still run it, from the window, after the trust
  dialog below. The report marks it.
- **Trust an author**: from the same dialog, scoped to one PR or to that author for 30 days; listed and revocable in
  Settings.
- **The sandbox**: builds and runs both happen inside it (Linux: bubblewrap; Windows: to be designed, see "Open").
  Network is off once submodules are fetched; the dump is read-only; nothing of the home directory is visible.
  What it does not stop is stated in the dialog and the README: a driver or kernel exploit through the GPU, and
  anything the tester runs with the sandbox off.

The trust dialog (blocking, not dismissible by Enter):

```
┌─ Run code nobody has checked? ───────────────────────────────────────────────┐
│                                                                              │
│  PR #8123 "perf(agc): …" by someuser has not been queued by an AnyPS5        │
│  maintainer. Nobody has checked this code for safety.                        │
│                                                                              │
│  If you continue, it will be built and run on this computer, with access to │
│  your GPU, inside a sandbox. The sandbox does NOT protect you from a          │
│  malicious driver or kernel exploit.                                         │
│                                                                              │
│  Results will be posted marked "run on the tester's trust".                  │
│                                                                              │
│  ( ) Run this PR's current head only                                         │
│  ( ) Trust someuser for this PR                                              │
│  ( ) Trust someuser for 30 days                                              │
│                                                                              │
│  [ ] I understand the risk       Type "someuser" to confirm: [__________]   │
│                                                                              │
│                                              [ Cancel ]   [ Run anyway ]     │
└──────────────────────────────────────────────────────────────────────────────┘
```

## The tester's experience

### First run: the walkthrough

Nothing runs until the tester has been through it once. One page each:

1. **What this does**: maintainers queue PRs; this machine builds and runs them on the tester's own dumps when it is
   free, and reports timings. What leaves the machine: the GitHub account, the machine's name, GPU, driver and OS
   (public, in the registration), timings, summary lines and outcome classes, and a screenshot only if enabled. Never
   game files.
2. **The sandbox**: builds and runs happen in bubblewrap with no network, no home directory and the dumps read-only.
   What it does not protect against: a driver or kernel exploit through the GPU, the display server, running out of
   disk or memory, and anything run with the sandbox off. The tester ticks that they have read it.
3. **When it may run**: on idle where the machine can tell (a desktop that reports idle to logind, or Windows); where
   it cannot (Hyprland without an idle daemon never sets logind's IdleHint), the page says so and the tester sets
   hours instead. Mains power only; pause while a fullscreen program or a game runs.
4. **Your dumps**: the client finds the titles and shows which have a route (full timing) and which get boot checks;
   the same page asks for the AnyPS5 clone (with submodules) that builds take main and the change from.
5. **Sign in with GitHub**: a code to type at github.com/login/device; the client shows who signed in.
6. **Register this machine**: the client opens the registration issue; the page shows "waiting for a maintainer" and
   the client goes to the tray. It takes jobs once a maintainer has approved the machine. Registering can wait (Settings
   has the same button); the walkthrough's last page says the machine takes no jobs until then.

### The tray

```
 ● AnyPS5 title runs                        tray menu
   ─────────────────────────────────────
   Running: #8104 · GTA V · main run 2/4
   Next: #7922 · GTA V (high)
   1 PR waiting for you
   ─────────────────────────────────────
   Testing: Off
 ✓ Testing: On schedule
   Testing: Now
   ─────────────────────────────────────
   Open…
   Quit
```

Dot: grey idle, green running, amber waiting for you, red error. A desktop notification when a job needs approval or
fails to build. The tray is optional (Settings, This app): without it, closing the window quits and stops the test.

### The window

A sidebar with four pages, and Maintainer tools in its own window for maintainers:

- **Home**: what this machine is doing in one line; the testing switch, **Off · On schedule · Now**, with what the
  chosen position means; Stop this test while one runs; the steps of the running test and the game itself, shown
  inside the window; Up next; Results (a local test's with its report).
- **Local tests**: below.
- **All pull requests** (the advanced view): the project's open PRs in four sections (queued by maintainers, mentions
  your titles, labelled perf/agc/shader, everything else); `Run…` on a not-checked PR opens the trust dialog.
- **Settings**: you and this machine (account, registration, the testing link), when to test, your games, the app
  (text size, the simple or advanced view, the tray), and in the advanced view the people you trusted and the logs.

## The report on the PR

One comment per PR from the App, edited as heads and machines report:

```
Title runs for 8d4f48671 (queued by @oneandonlydean, high)

Faster on 2 of 2 RTX 5060 Laptop · NVIDIA 615 · Linux machines, median −7.0 ms (−8.8 %)
No difference on 1 of 1 RTX 4060 · NVIDIA 580 · Linux machines, median −0.2 ms

| machine | GPU, driver, OS | title | outcome | p50 main → PR | verdict |
|---|---|---|---|---|---|
| laptop | RTX 5060 Laptop, 615.71, Linux | GTA V | renders | 79.7 → 72.4 ms | faster |
| laptop-2 | RTX 5060 Laptop, 615.71, Linux | GTA V | renders | 80.1 → 73.2 ms | faster |
| desktop | RTX 4060, 580.126, Linux | GTA V | renders | 95.0 → 94.8 ms | no difference |
| still wanted | amd, windows | any | | | |

<details> summary lines, per machine </details>
<details> earlier heads </details>
```

A new comment instead of an edit when an outcome changes (renders → crashes) or a verdict flips, because edits notify
nobody. Runs on a tester's own trust are listed separately, marked as such.

## Test setup (before anyone else sees it)

- Target: Charlie's fork `CPritch/AnyPS5`, with test PRs there (real upstream heads mirrored as fork branches).
- Maintainer: Charlie, labelling and commenting on the fork's PRs.
- App: `title-runs-dev` on Charlie's account, installed on the fork only.
- Results repository: `CPritch/anyps5-title-runs-results` (public).
- Testers: the laptop and the desktop.
- Done when: a tester onboards through the walkthrough and Charlie approves the machine with one label; a label on a
  fork PR gets both machines to claim, build, run and report in one edited comment; a push expires the label and
  the PR shows it; a command with `hw=` sends the job to the matching machine only; the trust dialog path posts a
  marked result; the overview shows all of it.

## What the current engine already does, and what changes

| | today | target |
|---|---|---|
| poll | GraphQL listing of PRs, debounce, supersede | read `queue.json` instead; poll PRs only for the tester's own browsing |
| trust | per-tester author allowlist, CLI confirm | maintainer queue by default; trust dialog for the rest |
| build | unsandboxed | in the sandbox, network off after submodules |
| run | sandboxed A/B with routes; #7264's boot checks | unchanged |
| report | rendered locally, dry-run poster with a tester token | result file pushed to the results repository; the App posts |
| UI | CLI and TOML | tray and window (PySide6); config written by the setup window |
| OS | Linux | Linux and Windows |

## Open

- **Windows sandbox.** Options: a restricted token / AppContainer for the run with GPU access, or a Windows Sandbox VM
  (vGPU support is limited). Until settled, Windows testers run maintainer-queued PRs only, and the dialog says the
  sandbox is weaker there.
- **Spam on public issues.** Anyone can comment on the job and registration issues. The workflow ignores what it
  does not accept, without a reply, and the Overview counts it. GitHub's interaction limits (up to six months, prior
  contributors only) would also block new testers' registrations, so they are left off.
- **Routes beyond GTA V.** Routes are per title and per tester's save; a small route recorder (press, wait for a frame
  state, mark) would let testers add their own.
- **Disk.** Two builds per job and warm caches per build; a cap with least-recently-used eviction.
- **What counts as a hardware class** (`hw=`): vendor and OS for a start; GPU family later.

## Round 3 decisions (Charlie, 2026-10-21)

1. **Too heavy for a maintainer to adopt, and no paid features.** Round 2 needed a webhook forwarder, a results
   repository with secrets and variables, a ruleset (a paid plan on a private repository) and a hand-made token per
   tester. Now: one App, one public repository, one secret, nothing hosted; testers sign in themselves and report
   as comments.
2. **Verdicts**: the 1 % rule per machine, combining same-class machines' differences, asking for another machine
   when borderline ("Verdicts").
3. **A first-run walkthrough** before anything runs ("First run: the walkthrough").
4. **Self-service for testers, an overview for maintainers**: registration by issue, approval by one label, the
   overview issue and tab, the label as the easy way to queue, and the label removed when a push expires an approval.

### Checked against GitHub's documentation

What each piece relies on, as GitHub documents it (2026-10-21), and what changed where it did not hold.

- **Device flow user tokens.** The device flow must be enabled in the App's settings and needs only the client ID
  (no secret). A user access token has only the permissions both the user and the App have, reaches only resources
  in accounts where the App is installed, and is attributed to the user (the App's badge beside them). It expires
  after 8 hours; the refresh token lasts 6 months, and refreshing a token that came from the device flow does not
  need the client secret. Holds: a desktop client can keep a tester signed in without shipping a secret. Rate limit:
  the user's own 5,000 requests an hour, shared with their other tools.
  Sources: "Generating a user access token for a GitHub App", "Refreshing user access tokens", "Authenticating with a
  GitHub App on behalf of a user".
- **Issues and comments.** Secondary limits: at most 80 content-creating requests a minute and 500 an hour, 900
  points a minute (writes cost 5), 100 concurrent requests. `GITHUB_TOKEN` has 1,000 requests an hour per
  repository; an App installation 5,000 (up to 12,500). A comment body is limited to 65,536 characters (GitHub's
  error message; not in the documentation). Holds: a job costs a tester two or three comments (claim, result, a
  withdrawal), and a result with four summary lines is under 10,000 characters; the workflow edits comments only when
  their text changes.
- **Scheduled workflows.** At most every 5 minutes; delayed under load, most at the start of every hour, and "some
  queued jobs may be dropped"; run from the default branch only; disabled in a public repository after 60 days
  without repository activity. Does not hold for anything that must react within minutes. Changed: nothing depends
  on one run happening on time. Claims are read directly from the job issue's comments, so two testers see each
  other at once; the workflow's state carries cursors, so a late or dropped run catches up; the cron minute avoids
  the hour; the overview shows when the workflow last ran, and the client warns when it is more than an hour old
  (a disabled schedule is re-enabled with one click in the Actions tab).
- **Labels and reactions.** Adding and removing a label on a PR needs the App's Issues and Pull requests write
  permissions; a reaction on a comment needs Issues write; the collaborator permission check needs Metadata read.
  Holds: the App can remove `title-test` and react to commands with the permissions above.
- **The head SHA of a label.** A polled `labeled` event carries the label, the actor and the time, but no PR head
  (its `commit_id` is for commits that reference the issue), and no event records when a regular (not forced) push
  happened. Does not hold for pinning by the event, which round 2 got from the webhook payload. Changed: the push
  time and pusher of a head come from the PR's workflow runs (`GET /repos/{o}/{r}/actions/runs?head_sha=`, readable
  by anyone on a public repository: `created_at`, `actor`, `event`); a head pushed after the label is not queued.
- **Branch protection.** The documentation states the plans for push restrictions (Free organisations' public
  repositories and up) but not clearly for personal accounts. No longer needed: testers have no write access, so
  only the workflow and the maintainers write the repository.
- **Pinning the overview issue.** Maintainers pin it once by hand; the workflow only edits its text.

## Round 4 decisions (Charlie, 2026-10-21)

Charlie's answers to round 3's questions.

1. **Where it lives.** The App and the results repository start on Charlie's account (`title-runs-dev`,
   `CPritch/anyps5-title-runs-results`, installed on CPritch/AnyPS5) and move to a maintainer once it works. The
   client has no built-in results repository: it takes it from its config, and switching to another one is one
   setting (Settings, or `title-runs client use OWNER/NAME`). The client starts afresh for the new repository:
   its checkout, registration and, when the new repository names another App, its sign-in.
2. **This repository becomes public** when the App is created, so the workflow can check it out at a pinned commit
   without a token. Before that, check it for anything that should not be public, and report it rather than
   rewriting history.
3. **An expired approval gets a new comment** as well as the label's removal: the maintainer has to act, and edits
   notify nobody.
4. **Comments the workflow does not accept get no reply.** They are ignored and counted in the Overview by reason,
   so nobody can make the workflow write by commenting. (Applied in the same way, not part of the answer: an
   `approved` or `declined` label from someone who isn't a maintainer is ignored and counted, not replied to.)
5. **A head with no PR workflow run is not approved by a label.** It needs `/title-test sha=<sha>`. The App removes
   the label and says so on the PR, in a new comment.
6. **The expired notice moves** from the top of the App's comment into its earlier-heads history once a new head is
   queued.
7. **Settings.** The 1 % threshold and the machines-per-class limit are `verdicts.threshold_pct` and
   `verdicts.class_max` in config.json, defaulting to 1 and 3.
8. **A disabled schedule.** The client keeps warning when the workflow hasn't run for an hour. The results
   repository's README says how to re-enable the schedule (the Actions tab, or `gh workflow enable relay`).

## Local tests and the testing switch (Charlie, 2026-10-22)

After the first night of local tests (17 upstream PRs, 2026-10-21).

1. **The testing switch** replaces Start, the automatic box and the tray's Pause: **Off** (no test starts), **On
   schedule** (tests start by themselves within When to test), **Now** (one test after another whatever the schedule
   says, until switched back). Switching doesn't end a running test; **Stop this test** does, and sets the switch to
   Off so nothing starts a minute later. A Pause from before the switch reads as Off.
2. **Local tests are a page of their own**, not a list in the config: add a PR by number or link, follow people (their
   open PRs), test again, remove (a followed person's PR then stays off). Each PR shows its newest result, and its
   earlier ones in the report window.
3. **Fixes on both sides.** PRs merged onto main for both sides, for a main that can't run the tester's games without
   them (main aborted GTA V at boot from fe4016f61 until #9730). A fix main already has is left out; a fix that
   doesn't merge, or whose head its author didn't push, holds local tests and says why.
4. **A main that doesn't start the game holds local tests only**, until main is pinned again (12 hours, or Use the
   latest main) or the fixes change. The queue's tests, on their own main, go on.
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
