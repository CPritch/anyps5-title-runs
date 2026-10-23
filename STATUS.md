# Status (2026-10-23)

Where the tool stands. DESIGN.md has the decisions and why; README.md how to use it.

## Works

- **The queue, on GitHub** (CPritch/AnyPS5 and its public results repository, with the App `title-runs-dev`), since the
  first real test on 2026-10-21: the App from its manifest, device-flow sign-in, registration approved by label, a
  label queueing a pull request, a tester's claim, build, A/B and result on the pull request, a push expiring the
  approval, and the re-label queueing the new head.
- **Local tests of upstream AnyPS5**: 17 pull requests tested overnight on 2026-10-21, fixes carried on both sides,
  reports in the project's form, posting by hand, stale results, and testing again keeping the earlier result.
- **Reports with their traces**: one trace per run under GitHub's 25 MB (the window sized to fit), each trace's digest,
  the traces named by run and linked into one folder to drag into the comment. First used on #4287 on 2026-10-23.
- **Scenarios**: GTA V's prologue (the default, no save) and Franklin's front door (a PS4 100% save, downloaded and
  checked against its sha256), each run checked to be in its scene.
- **Local tests only**, for a project that hasn't set up the queue: a config with no results repository and the App
  to sign in with.
- **The window**: Home, Local tests, All pull requests, Settings and Maintainer tools; the game shown inside it.
- **The command line**: every command the window has, with `--json`, self-describing help and docs/CLI.md made from
  the commands; it can run alongside the window.
- **Tests**: 238 (`python3 -I -m unittest discover -s tests -t tests`).

## Open

- **The house scenario isn't fit for verdicts**: GTA V picks a camera framing at each load (main's two runs 86.8 and
  92.0 ms). Repeatable runs need saves in missions, and none are published decrypted: they would come from play, as
  would recorded input for longer runs.
- **Dragging traces from the window into a browser** is untested (the window and Chrome are both X11 windows here).
- **GitHub's schedule runs the relay hours apart** (11 runs from 21 to 23 October, 2 to 6 hours apart, for a schedule of
  every 5 minutes). The window no longer starts it with `gh workflow run`, so a label waits for the next of those runs.
- **Not built yet**: posting a report through a narrowly scoped App with the tester's approval for each post, spotting
  reports posted by hand, and a packaged release.
- **Not run yet**: Windows.
- `docs/screens/` shows the round-3 window.
