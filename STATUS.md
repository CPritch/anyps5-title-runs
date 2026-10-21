# Status: round 4 (2026-10-21), for Charlie's review

Round 4 builds Charlie's answers to round 3's questions (DESIGN.md, "Round 4 decisions") and prepares the first real
test (docs/first-real-test.md). Nothing has been created on GitHub and nothing posted. The REST code's reads were
run against the real fork and upstream (GET only), and the workflow's steps were rehearsed locally in dry-run mode.

## Round 4

- **The results repository from the config only**: OWNER/NAME accepted. `title-runs client use` or the Settings
  field switches, all or nothing. Registration is per repository, and a sign-in is kept only for the same App.
- **An expired approval and a refused label get a new App comment.** A head without a PR workflow run needs
  `/title-test sha=`; the commit-date fallback is gone. The expired notice moves into "Earlier heads" once a new
  head is queued.
- **No replies to what the workflow doesn't use.** It is counted by reason in the Overview issue and tab, and a
  tester's client shows that tester their own ignored comment.
- **`verdicts.threshold_pct` and `verdicts.class_max`** in config.json, defaulting to 1 and 3.
- **A disabled schedule:** the client warns, and the results repository's README says how to re-enable it.
- **Checked against real GitHub (read-only):**
  - comments are now read by creation time, since GitHub's `since=` returned every old comment edited later;
  - `relay poll --dry-run` reads the real repositories and records what it would write;
  - the patch-id comparison is capped at 100 own commits, because a stale main made it outlast the workflow's
    timeout;
  - a stored sign-in that names no App now needs a new one.
- **The App from its manifest:** `title-runs app create`. The device flow and the installation are left as two
  clicks the manifest cannot do. `export-results-repo --git` makes the ready-to-push results repository.
- **Tests:** 160.

## Works on the laptop

- **GitHub behind one interface** (`gh.py`): the REST calls the workflow and the client make, and a fake of both
  repositories with accounts, permissions, workflow runs and the device flow. The stand-in and the tests use the fake.
- **The relay workflow** (`relay/`, `results_repo/`), one scheduled workflow with one secret:
  - It polls labels, commands and new heads, and pins a label to the head pushed before it, using the PR's workflow
    runs.
  - A push after approval carries the approval over or expires it. On expiry the App removes the label and says on
    the PR which commit expired it.
  - It handles registration issues approved by a label, job issues, and results from comments. A result is accepted
    only from a registered machine with a live claim.
  - It edits the App's comment on the PR and the Overview issue.
- **Verdicts** (`verdict.py`): the 1 % rule per machine, classes combined by their differences, and a borderline
  class asking the scheduler for one more machine of it.
- **The client** (`client.py`, `auth.py`, `store.py`): device-flow sign-in, registration, and claims, withdrawals and
  results as comments. It reads only the public checkout of the results repository. A machine's result ends its
  claim. Nothing runs before the walkthrough is done, the tester is signed in and the machine is approved.
- **The window**:
  - the walkthrough (7 pages);
  - the Queue tab, with a banner saying why the machine takes no jobs;
  - the Overview tab, with Approve and Decline for maintainers;
  - Settings, with the account and the registration;
  - Schedule, with idle detection shown as not available on this laptop, and the fullscreen pause through hyprctl.
- **End to end on the laptop** (docs/e2e-2026-10-21-round3/), against the stand-in:
  - A new tester went through the walkthrough, signed in and registered, and CPritch approved the machine from the
    Overview tab.
  - A label queued #8104 at 69ac2e155.
  - The laptop ran it for real: main 77.7/77.8 ms, PR 77.7/78.0 ms, "no difference". The result showed on the PR and
    in the overview.
  - A synthetic second machine of the class made it borderline. The scheduler then asked for a third machine of the
    class (laptop-2, with round 2's real numbers for the same commit), and that settled it at "No difference on 2 of
    3 … machines, median -0.34 ms".
  - The author's push of 8118a04e4 expired the approval. The App removed `title-test` and named the commit on the
    PR, and the label queued the new head again.
- **Tests (round 3):** 138.

## Not done or stubbed

- No write to GitHub has been made, and the App and the results repository don't exist yet. `gh.GitHubRepo`'s reads
  were run against real repositories, and `relay.yml`'s steps rehearsed locally. Its writes, the device flow
  against github.com, `create-github-app-token` and the workflow on Actions have not run.
- Only the laptop's run in the end-to-end test was measured today. The other two machines are real clients, each
  with its own sign-in, registration, claim and result comment, but `job.run` was replaced:
  - `synthetic` carries today's laptop numbers with the PR's p50 lowered by 1.5 ms (made up, to make the class
    disagree);
  - `laptop-2` carries the laptop's real round-2 run of the same commit.
- The relay's replies to comments it does not accept (not registered, no claim) are written. Nothing limits how many
  replies one account can draw ("Open" below).
- The walkthrough checks that an AnyPS5 clone exists but doesn't make one. A new tester needs a clone with its
  submodules, and on this laptop an unpacked ffmpeg package (`source.cmake_args`), set up by hand.
- These are shown and saved but not acted on:
  - the Titles tab's on/off and seed saves;
  - the Schedule tab's disk and longest-job limits;
  - "Also a screenshot": no screenshot is uploaded.
- Windows: platform_info's Windows paths (idle, fullscreen, power) are written but have not been run. There is no
  Windows sandbox.
- The Stop button and a superseded head take effect between runs, not inside one.
