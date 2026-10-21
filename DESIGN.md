# Design: title runs for AnyPS5 pull requests

Status: draft for Charlie's review, 2026-10-21. It describes the tool we are aiming for. The code in this repository
today is the first engine (poll, build, sandboxed A/B, report); STATUS.md says where it stands.

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
2. **Testers never hold a key to the repository.** Results reach GitHub through a maintainer-owned relay; the bot is
   a GitHub App the maintainers own.
3. **Easy and quiet.** Install, point it at your dumps, leave it running. It works when the machine is idle, gets out
   of the way when you use it, and asks you something only when it must.
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
 GitHub (boykopovar/AnyPS5)          maintainer-owned                      tester's machine
 ─────────────────────────          ────────────────                      ────────────────
 PR #8104                           results repository                    client (tray + window)
  label  title-test   ─────────▶    queue.json  ◀── App workflow           │ reads queue.json (public read)
  /title-test high hw=amd ──────▶   (from labels and commands)             │ claims a job (claim file)
                                    claims/<job>/<machine>.json ◀──────────┤ builds + runs in the sandbox
  bot comment (edited)  ◀────────   results/<job>/<machine>.json ◀─────────┘ pushes results (scoped token)
                          App       workflow: validate, render, post as the App
```

- **The App** (owned by a maintainer; built and tested first on Charlie's account against his fork, then transferred).
  Permissions: Pull requests read and write (comments), Issues read and write (comments go through the issues API),
  Metadata read. Nothing on contents. Installed only on boykopovar/AnyPS5 by its owners.
- **The results repository** (maintainer-owned). Holds `queue.json`, claims and results. Its Actions workflows run on
  GitHub's own hosted machines (no self-hosted runners) and hold the App's private key as a secret:
  - *queue*: on a label or a comment command on AnyPS5 (from a maintainer only, by `author_association` and an
    explicit maintainer list), update `queue.json`;
  - *publish*: on a pushed result, check it against the queue and the claim, render the comment, post or edit it as
    the App.
- **Testers' tokens** write only to the results repository, and only under `claims/` and `results/` (a fine-grained
  token per tester, or per-tester deploy keys; to be settled). The maintainer revokes a tester by deleting it.
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

- **Claims and leases.** Before building, the client writes a claim (`claims/<job>/<machine>.json`) with an expiry
  (default 3 hours); the queue workflow ignores expired claims. Two testers of the same class do not run the same
  head at once.
- **New heads.** A new head of a queued PR supersedes the old one; a running job for the old head finishes its
  current run and stops.

## Trust and safety

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

### First run

1. Install (a package per platform; Python and PySide6 bundled).
2. A setup window: pick the folder with your dumps; the client finds the titles (extracted packages:
   `eboot.bin`, `sce_sys/param.json`), shows which have a route (full timing) and which get boot checks; detects the
   GPU, driver and OS; asks for a machine name.
3. Connect to the results repository (paste the token the maintainer gave you, or a sign-in flow if we can make one
   work). The client checks it can read the queue and write a claim.
4. Pick a schedule (default: when idle, on mains power). Done; it goes to the tray.

### The tray

```
 ● AnyPS5 title runs                        tray menu
   ─────────────────────────────────────
   Running: #8104 · GTA V · main run 2/4
   Next: #7922 · GTA V (high)
   1 PR waiting for you
   ─────────────────────────────────────
   Pause for 1 hour
   Pause until I resume
   Open…
   Quit
```

Dot: grey idle, green running, amber waiting for you, red error. A desktop notification when a job needs approval or
fails to build.

### The window

Tabs:

- **Queue**: running (with a progress line and a Stop button), up next (the score's reasons on hover), waiting for
  you, recently posted (with links to the comments).
- **Pull requests**: for choosing work outside the queue.

  ```
  ┌ Pull requests ─────────────────────────────────────── [ search… ] ┐
  │ ▼ Queued by maintainers (3)                                          │
  │   #7922  span single-wave wave64 compute…   high   GTA V   ✓ queued  │
  │   #8104  stage written elements…            normal any     ✓ queued  │
  │ ▼ Mentions your titles (2)                                           │
  │   #6488  run waterfall loops over per-lane… Unblocks PPSA04264       │
  │         ⚠ not checked                                    [ Run… ]    │
  │ ▶ Labelled perf, agc or shader (41)                                  │
  │ ▶ Everything else (512)                                              │
  └──────────────────────────────────────────────────────────────────────┘
  ```

  `Run…` on a not-checked PR opens the trust dialog.
- **Schedule**: when work may run (idle only; hours per day; mains power only); pause while a fullscreen app or a game
  is running; limits (disk for builds and caches, longest job).
- **Titles**: detected dumps; route or boot check; seed saves; per title on or off.
- **Settings**: machine name, results repository connection, sandbox status (with a self-test), what is posted
  (screenshots on or off), trusted authors (revoke), logs.

## The report on the PR

One comment per PR from the App, edited as heads and machines report:

```
Title runs for 8d4f48671 (queued by @oneandonlydean, high)

| machine | GPU, driver, OS | title | outcome | p50 main → PR | verdict |
|---|---|---|---|---|---|
| laptop | RTX 5060 Laptop, 615.71, Linux | GTA V | renders | 79.7 → 72.4 ms | faster |
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
- Results repository: `CPritch/anyps5-title-runs-results` (private).
- Testers: the laptop and the desktop.
- Done when: a label on a fork PR gets both machines to claim, build, run and report in one edited comment; a new
  head edits it; a command with `hw=` sends the job to the matching machine only; the trust dialog path posts a
  marked result.

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
- **Tester credentials.** Fine-grained tokens on the results repository versus deploy keys versus a device sign-in.
- **Routes beyond GTA V.** Routes are per title and per tester's save; a small route recorder (press, wait for a frame
  state, mark) would let testers add their own.
- **Disk.** Two builds per job and warm caches per build; a cap with least-recently-used eviction.
- **What counts as a hardware class** (`hw=`): vendor and OS for a start; GPU family later.
