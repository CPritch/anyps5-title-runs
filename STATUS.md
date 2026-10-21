# Status: round 3 (2026-10-21), for Charlie's review

Round 3 builds Charlie's four decisions (DESIGN.md, "Round 3 decisions"): one App, one public repository and one secret;
verdicts across machines of a class; a first-run walkthrough; self-service for testers and an overview for maintainers.
It was built and proved against the local stand-in only. Nothing has been created on GitHub, nothing posted, and
nothing has run on GitHub Actions.

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
- **Tests:** 138.

## Not done or stubbed

- Nothing has talked to GitHub. `gh.GitHubRepo`, the device flow against github.com and `relay.yml` on Actions are
  written, not run. The App and the results repository don't exist yet.
- Only the laptop's run in the end-to-end test was measured today. The other two machines are real clients, each
  with its own sign-in, registration, claim and result comment, but `job.run` was replaced:
  - `synthetic` carries today's laptop numbers with the PR's p50 lowered by 1.5 ms (made up, to make the class
    disagree);
  - `laptop-2` carries the laptop's real round-2 run of the same commit.
- The relay's replies to comments it does not accept (not registered, no claim) are written. Nothing limits how many
  replies one account can draw ("Open" below).
- The walkthrough checks that an AnyPS5 clone exists but doesn't make one. A new tester needs a clone with its
  submodules, and on this laptop an unpacked ffmpeg package (`source.cmake_args`), set up by hand.
- A new config needs `--results URL`: no default results repository is built in.
- These are shown and saved but not acted on:
  - the Titles tab's on/off and seed saves;
  - the Schedule tab's disk and longest-job limits;
  - "Also a screenshot": no screenshot is uploaded.
- Windows: platform_info's Windows paths (idle, fullscreen, power) are written but have not been run. There is no
  Windows sandbox.
- The Stop button and a superseded head take effect between runs, not inside one.
