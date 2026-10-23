# Status (2026-10-23)

Where the tool stands. DESIGN.md has the decisions and why; README.md how to use it.

## Works

- **Local tests of upstream AnyPS5**: 17 pull requests tested overnight on 2026-10-21, fixes carried on both sides,
  reports in the project's form, posting by hand, stale results, and testing again keeping the earlier result.
- **Reports with their traces**: one trace per run under GitHub's 25 MB (the window sized to fit), each trace's digest,
  the traces named by run and linked into one folder to drag into the comment. First used on #4287 on 2026-10-23.
- **Scenarios**: GTA V's prologue (the default, no save) and Franklin's front door (a PS4 100% save, downloaded and
  checked against its sha256), each run checked to be in its scene.
- **The window**: Home, Local tests, All pull requests (with Add) and Settings; the game shown inside it.
- **The command line**: every command the window has, with `--json`, self-describing help and docs/CLI.md made from
  the commands; it can run alongside the window. No command writes to GitHub.
- **Tests**: 126 (`python3 -I -m unittest discover -s tests -t tests`).

## Taken out (2026-10-23)

The queue: the results repository and its relay workflow, registering machines, the App queueing and commenting on
pull requests, the stand-in, and the window's Maintainer tools (DESIGN.md, "Local tests alone"). On GitHub, the results
repository CPritch/anyps5-title-runs-results and the App's permissions are Charlie's to retire; until then the
repository's relay still runs on GitHub's schedule, hours apart.

## Open

- **The house scenario isn't fit for verdicts**: GTA V picks a camera framing at each load (main's two runs 86.8 and
  92.0 ms). Repeatable runs need saves in missions, and none are published decrypted: they would come from play, as
  would recorded input for longer runs.
- **Signing in for anyone else**: the tool's App, title-runs-dev, is private, and a private App can be authorized only
  by its owner (GitHub's "Making a GitHub App public or private"). Another tester needs it public, or an App of their
  own in `[github] app`.
- **Dragging traces from the window into a browser** is untested (the window and Chrome are both X11 windows here).
- **Not built yet**: spotting reports posted by hand, a packaged release, and renting machines (Vast).
- **Not run yet**: Windows.
