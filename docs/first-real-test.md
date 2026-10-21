# The first real test: checklist and plan

Everything below was prepared on the laptop on 2026-10-21; nothing has been created on GitHub yet. In order, each
step says what to do and how to check that it worked. Commands assume this repository is at
`~/src/anyps5-title-runs` and the AnyPS5 clone at `~/src/AnyPS5` (remote `fork` = CPritch/AnyPS5).

What is ready:

| what | where |
|---|---|
| the results repository, one commit, tool pinned at `56ce7155d` | `~/games/title-runs-first-test/results` |
| the laptop's client config (real GitHub, the warm builds and caches) | `~/games/title-runs-first-test/laptop.toml` |
| the test PR's later, doc-only commit (CPritch, on `69ac2e155`) | `~/src/AnyPS5`, branch `title-runs/first-test-push`, `ed127b213` |
| the App manifest (printed, not sent) | `title-runs app manifest --results-repo ~/games/title-runs-first-test/results` |

The names: the App `title-runs-dev`; the results repository `CPritch/anyps5-title-runs-results` (public); AnyPS5 is
the fork `CPritch/AnyPS5`; the maintainer and both testers are `CPritch` (machines `laptop` and `desktop`).

## Before anything: decide on the public check

This repository goes public in step 3. The round-4 report on the board lists what would become public with it
(commit metadata, local paths and names in the evidence and screenshots, the vendored code and its licences). Decide
on each before step 3.

## A. The App

1. **Create it from the manifest.**

   ```
   cd ~/src/anyps5-title-runs
   python3 -I title-runs app create --results-repo ~/games/title-runs-first-test/results --out ~/games/title-runs-first-test/app
   ```

   A browser page opens (127.0.0.1). Press **Continue to GitHub**, check what GitHub shows, and press **Create GitHub
   App for CPritch**. The page that comes back links to steps 2 and 5.

   Check: the page says "Created title-runs-dev" with an App ID. `~/games/title-runs-first-test/app/` holds
   `app.json` and `title-runs-dev.private-key.pem` (mode 600). `git -C ~/games/title-runs-first-test/results log
   --oneline` shows a second commit, "config.json: the App title-runs-dev (…)".
2. **Turn on the device flow.** On https://github.com/settings/apps/title-runs-dev, under "Identifying and
   authorizing users", tick **Enable Device Flow** and press **Save changes**. The manifest cannot set this.

   Check: after reloading, the box is still ticked. On "Permissions & events": Actions read-only, Issues read and
   write, Pull requests read and write, Metadata read-only. Under General, Webhook is not active.
3. **Make this repository public**, so the workflow can check it out at the pinned commit without a token:
   `gh repo edit CPritch/anyps5-title-runs --visibility public --accept-visibility-change-consequences`.

   Check: `gh repo view CPritch/anyps5-title-runs --json visibility` says PUBLIC, and
   https://github.com/CPritch/anyps5-title-runs/commit/56ce7155dc1123936bcf19d2e1524ac24bf4afe9 opens when signed out.

## B. The results repository

4. **Create it from the prepared folder:**

   ```
   gh repo create CPritch/anyps5-title-runs-results --public --source ~/games/title-runs-first-test/results --push \
     --description "AnyPS5 title runs: the queue, the registered machines and the results"
   ```

   Check: the repository shows `config.json`, `README.md` and `.github/workflows/relay.yml`, and `config.json` has the
   App's ID (step 1 committed it).
5. **Install the App.** On https://github.com/apps/title-runs-dev/installations/new, pick CPritch, choose **Only
   select repositories**, pick **AnyPS5** and **anyps5-title-runs-results**, and press **Install**. Both are needed:
   the workflow acts on AnyPS5 as the App, and testers' sign-ins reach only repositories the App is installed on.

   Check: https://github.com/settings/installations lists title-runs-dev with 2 repositories.
6. **The one secret:**
   `gh secret set APP_PRIVATE_KEY -R CPritch/anyps5-title-runs-results < ~/games/title-runs-first-test/app/title-runs-dev.private-key.pem`

   Check: `gh secret list -R CPritch/anyps5-title-runs-results` shows APP_PRIVATE_KEY.
7. **Labels** (the workflow and testers use them; creating them first avoids relying on GitHub creating them on use):

   ```
   for l in registration approved declined job overview tester-trust; do gh label create $l -R CPritch/anyps5-title-runs-results; done
   gh label create title-test -R CPritch/AnyPS5 --color 5319e7 --description "Queue this PR's head for title runs"
   ```

   Check: `gh label list -R CPritch/anyps5-title-runs-results` shows the six; `gh label list -R CPritch/AnyPS5
   --search title-test` shows one.
8. **The first workflow run:** `gh workflow run relay -R CPritch/anyps5-title-runs-results`, then
   `gh run watch -R CPritch/anyps5-title-runs-results`.

   Check: the run succeeds. The repository has two issues, "Runs on testers' own trust" and "Overview", and a new
   commit, "relay: …", with `queue.json`, `registry.json` and `cursors.json`. **Pin the Overview issue** (its page,
   Pin issue). After that the schedule runs it every 5 minutes; a new repository's schedule can take a while to
   start, and `gh workflow run relay` runs it at once whenever the test should not wait.

   If it fails:
   - at "The App's token": the App isn't installed on AnyPS5 (step 5), or the secret isn't the whole key file;
   - at "Check out the tool": step 3 isn't done;
   - at "Relay": the log says which call failed.

## C. The fork

9. **Main at the commit the test is measured against.** d97361bd0 is upstream main from 2026-10-20 23:54. GTA V
   renders on it, and the laptop's builds and caches for it are warm. It fast-forwards from the fork's main
   (c4708fa20):

   ```
   git -C ~/src/AnyPS5 push fork d97361bd0df0a54b11570602391aa003bff31047:refs/heads/main
   ```

   Check: `gh api repos/CPritch/AnyPS5/branches/main --jq .commit.sha` prints d97361bd0df0….

   The fork already runs upstream's scheduled workflows (labels, PR overlap, conflict checks); they keep running and
   may label or comment on the test PR. Upstream's `pr-intake` closes PRs beyond the first from an author with no
   merged PR there, so keep only this one PR open on the fork.

## D. The testers

10. **The laptop.**
    `python3 -I ~/src/anyps5-title-runs/title-runs ui --config ~/games/title-runs-first-test/laptop.toml`

    The walkthrough opens (its client state from the stand-in rounds was moved to `client-round3`). On the sign-in
    page, open github.com/login/device, enter the code, and authorize title-runs-dev as CPritch. Register the machine
    as `laptop`.

    Check: Settings says "waiting for a maintainer (#N)", and the results repository has an issue
    "Machine: CPritch/laptop".
11. **The desktop** (RTX 4060, NVIDIA 580, Linux Mint):
    - `gh repo clone CPritch/anyps5-title-runs ~/src/anyps5-title-runs` (it is public after step 3).
    - Python 3.11 or later; `sudo apt install bubblewrap`.
    - Check that the sandbox can start: `bwrap --unshare-all --ro-bind / / --dev /dev true && echo ok`. Mint is
      built on Ubuntu, and Ubuntu 24.04 can block unprivileged user namespaces (`sysctl
      kernel.apparmor_restrict_unprivileged_userns`). If the command fails, that is the cause: it needs an AppArmor
      profile for bwrap, or the setting off.
    - A config like the laptop's: copy `laptop.toml` and change `state_dir`, `[tester] machine = "desktop"`,
      `[machine]` (or delete it to have it detected), `[source] repo_dir` and `cmake_args` (the desktop's own
      ffmpeg setting), and `[titles.PPSA04263]` `dump` and `seed` (the desktop's dump and the harness's saves).
    - Then the same as the laptop: `title-runs ui --config …` (PySide6), or without the window:
      `title-runs client --config … sign-in`, then `… register`.

    Check: an issue "Machine: CPritch/desktop".
12. **Approve both machines:** add the label `approved` to each registration issue, or press Approve in the Overview
    tab (as a maintainer). Then wait for the next run, or `gh workflow run relay`.

    Check: the Overview issue lists CPritch/laptop and CPritch/desktop under Machines, the issues are closed with
    "Approved by @CPritch", and the clients' Queue banner no longer says "takes no jobs yet".

## E. The test

The PR mirrors boykopovar/AnyPS5#8104 at **69ac2e155**: its head on 2026-10-19 (upstream has since rebased it to
5804207c5, whose patch-ids differ). GTA V renders with it merged onto d97361bd0: rounds 2 and 3 on the laptop, 4/4
runs counted each time. The later push is a doc-only commit by CPritch, **ed127b213**, so its A/B is a no-op control.

13. **Open the PR:**

    ```
    git -C ~/src/AnyPS5 push fork 69ac2e155ad018ed1fb9028d2028d15999a8571e:refs/heads/title-runs/8104-mirror
    gh pr create -R CPritch/AnyPS5 --base main --head title-runs/8104-mirror \
      --title "[title-runs test] mirror of boykopovar/AnyPS5#8104 at 69ac2e155" \
      --body "A test PR for anyps5-title-runs on this fork only: upstream's #8104 at 69ac2e155, by Celegans12. Not for merging."
    ```

    Check: `gh run list -R CPritch/AnyPS5 --commit 69ac2e155ad018ed1fb9028d2028d15999a8571e` lists runs (Build and
    others; whether they pass doesn't matter). A run is what tells the workflow when this head was pushed.
14. **Label it** `title-test` (on the PR page). Within 5 minutes, or at once with `gh workflow run relay -R
    CPritch/anyps5-title-runs-results`:
    - the App comments "Queued `69ac2e155` for title runs: approved by @CPritch (label, …)";
    - the results repository has an issue "Job <n>-69ac2e155ad0", where <n> is the PR's number on the fork, likely 1;
    - the Overview lists it, with 2 machines wanted.

    If the App instead says the head "has no PR workflow run", comment `/title-test sha=69ac2e155` on the PR.
15. **Run it on both machines:**
    `python3 -I ~/src/anyps5-title-runs/title-runs client --config <the machine's toml> run-once --ignore-schedule`.
    Use `--ignore-schedule` because the laptop's hours are 01-07: it can't detect idle. Or leave the tray running with
    `--auto` within the hours.
    - Laptop: about 15 minutes, as main d97361bd0 and the merge f0a2a25b4 are warm.
    - Desktop: both builds and the warm-ups are new, about an hour.

    Check: the job issue has a claim and a result from each machine. The App's comment edits to two rows in two
    classes, "RTX 5060 Laptop GPU · NVIDIA 615 · Linux" and "RTX 4060 · NVIDIA 580 · Linux", each "… on 1 of 1".
    The Overview shows both machines' last report.
16. **The push that expires it:**
    `git -C ~/src/AnyPS5 push fork ed127b213c404adc74fefe5d2d4a1d0481892438:refs/heads/title-runs/8104-mirror`
    (a fast-forward). Within 5 minutes:
    - the label is gone from the PR (its timeline shows title-runs-dev removing it);
    - a **new** App comment says "**Approval of `69ac2e155` expired**: `ed127b213` was pushed after it by @CPritch
      (…) and is not checked";
    - the job issue is closed with "Approval expired …";
    - the Overview lists it under "Approvals a push expired".

    A client in the middle of a run stops after that run, and nobody starts the old head again.
17. **Label it again.** Within 5 minutes:
    - "Queued `ed127b213`";
    - the expired notice has left the top of the App's comment and is under "Earlier heads";
    - a new job issue.

    Run both machines again (step 15). The doc-only change should come out as "no difference" on both.
18. **Afterwards:** close the PR, and delete the branch `title-runs/8104-mirror` on the fork. Keep or delete the
    results repository and the App; they cost nothing. The laptop's session can collect the evidence afterwards
    with read-only `gh api` calls.

## What to watch for

- **The schedule:** GitHub may run it late or skip a run; `gh workflow run relay` always works. The Overview's
  "Updated by the relay workflow at …" line shows the last run.
- **Sign-in:** if github.com/login/device rejects the code, the device flow is off (step 2). If a client says "not
  signed in" after switching repositories, sign in again.
- **Nothing gets an answer** in the results repository unless the workflow used it. A tester whose comment was
  ignored sees why in their client's Queue tab, and the Overview counts it.
- **Before trying it on upstream AnyPS5**, check the fork's results first: `title-runs relay poll --dry-run OUTBOX`
  against a copy of the state shows what the workflow would write, without writing.
