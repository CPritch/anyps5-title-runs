# Status: round 2 (2026-10-21), for Charlie's review

Built toward DESIGN.md (f1b2b3c, with e2c25ff's per-commit approval) against a local stand-in for GitHub and the results
repository. Nothing has been posted to GitHub and nothing has run on GitHub Actions.

## Works on the laptop

- The queue and scheduling (formats.py, schedule.py; FORMATS.md): queue.json pins the approved SHA, claims with expiry,
  results, the score per DESIGN.md.
- The workflows' logic (relay/), tested against webhook-shaped fixture events and a fake GitHub: labels and
  /title-test commands from maintainers only, per-commit approval with patch-id and collaborator carry-over, pushes
  after approval kept "not checked", publish checks against claim, pusher and approved heads, one comment per PR with
  the new-or-edit rule. The workflow files (results_repo/) parse and run the tool from a pinned commit.
- Builds in the build sandbox (no network, GPU or display); a build that reaches for the network fails.
- The client: claim, fetch the approved SHA and main, merge locally, check again, build, run, push, withdraw the claim
  when the queue moved on.
- The tray, the window, the trust dialog and the first-run setup (PySide6); screenshots in docs/screens/.
- End to end with the stand-in (docs/e2e-2026-10-21/): label -> claim -> sandboxed build and A/B on GTA V -> result ->
  comment; a push after approval shown as not checked; a maintainer's sha= approval; the second head's run edits the
  comment with the first head under Earlier heads.
- 117 tests.

## Not done or stubbed

- Nothing has talked to GitHub: GitHubForge (the App's REST calls), the https results repository with a tester token,
  and the workflows on Actions are written, not run.
- The App's webhook has nowhere to go: the queue workflow takes events as repository_dispatch, which needs a small
  forwarder (or GitHub's webhook redelivery into Actions some other way). Without it only the 10-minute refresh runs,
  which follows pushes to queued PRs but does not see new labels or commands.
- Idle detection on Linux reads logind's IdleHint; on this laptop nothing sets it (no idle daemon), so "only when
  idle" never lets a job start. The end-to-end runs used `client run-once --ignore-schedule`.
- The Titles tab's on/off and seed saves, and the Schedule tab's disk and longest-job limits, are shown and saved but
  not acted on. "Also a screenshot" is saved; no screenshot is uploaded.
- The trust dialog path is tested with a fake job (tests/test_client.py), not run end to end with a real build.
- Windows: platform_info's Windows paths are written, not run; no Windows sandbox (DESIGN.md, "Open").
- The Stop button and a superseded head take effect between runs, not inside one. Claim renewal is written, not tested.
