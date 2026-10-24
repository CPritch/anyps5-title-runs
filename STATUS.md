# Status (2026-10-23)

Where the tool stands. DESIGN.md has the decisions and why; README.md how to use it.

## Works

- **Local tests of upstream AnyPS5**: 17 pull requests tested overnight on 2026-10-21, fixes carried on both sides,
  reports in the project's form, posting by hand, stale results, and testing again keeping the earlier result.
- **Reports with their traces**: one trace per run under GitHub's 25 MB (the window sized to fit), each trace's digest,
  the traces named by run and linked into one folder to drag into the comment. First used on #4287 on 2026-10-23.
- **Scenarios**: GTA V's prologue (the default, no save) and Franklin's front door (a PS4 100% save, downloaded and
  checked against its sha256), each run checked to be in its scene.
- **Recording a scenario** (2026-10-23): a controller's play recorded from a scenario's scene and played back in every
  run of the new scenario (DESIGN.md, "Recorded play"). Tested in GTA V with a scripted controller: the input walks
  Franklin out of his house, and the playback follows it. Not yet with a real controller, and no timed A/B has run in a
  recorded scenario yet. GTA V's autosave prompt stops a walk out of Franklin's house about 25 s in, unless autosave is
  off in the profile save.
- **Reading GitHub without a sign-in**: heads from git; a refresh of 17 pull requests and a fix cost one API request
  on 2026-10-23, and All pull requests' Refresh 14 (AnyPS5's 1,314 open pull requests, in 14.5 s).
- **The window**: Home, Local tests, All pull requests (with Add, read on Refresh) and Settings; the game shown inside
  it.
- **The command line**: every command the window has, with `--json`, self-describing help and docs/CLI.md made from
  the commands; it can run alongside the window. No command writes to GitHub.
- **Tests**: 126 (`python3 -I -m unittest discover -s tests -t tests`).

## Taken out (2026-10-23)

The queue: the results repository and its relay workflow, registering machines, the App queueing and commenting on
pull requests, the stand-in, and the window's Maintainer tools (DESIGN.md, "Local tests alone"). Then the sign-in and
the App (DESIGN.md, "Reading GitHub without a sign-in"). On GitHub, the results repository
CPritch/anyps5-title-runs-results and the App title-runs-dev are Charlie's to delete; until then the repository's relay
still runs on GitHub's schedule, hours apart.

## Open

- **The house scenario**: GTA V picks a camera height and pitch at each load (main's two runs 86.8 and 92.0 ms). Its
  start now sets the camera the same way in every run (DESIGN.md, "Charlie's walk, the pad reads and a set start");
  seven timed runs with an earlier start were 82.2 to 86.1 ms, and the spread still followed the camera. Not yet
  timed enough with the current start to say whether it is fit for verdicts.
- **A timed run's window can come before the route is done**: with a window from a quick warm-up and slow menus, the
  frame dumps stop before the route sees Resume Story's load (5 of 16 runs on 2026-10-24, none of 137 before).
- **Recorded play reproduces deliberate play, not long free play**: input lands on the same pad reads every run, but
  a frame's timing error per stick change compounds; exact frames need an AnyPS5 change.
- **Dragging traces from the window into a browser** is untested (the window and Chrome are both X11 windows here).
- **Not built yet**: spotting reports posted by hand, a packaged release, and renting machines (Vast).
- **Not run yet**: Windows.
