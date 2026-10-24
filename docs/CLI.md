# The title-runs command line

Made by `title-runs help --markdown` from the commands themselves (title_runs/cli.py); a test checks it is current.

```
title-runs: test AnyPS5 pull requests on your own games and hardware, against main.

Usage: title-runs [--config FILE] [--json] COMMAND [ARGS]

This computer
  status                  What this computer is doing: the test running, the testing switch, what's next, anything to fix.
  testing                 Show or set the testing switch: off, schedule or now.
  stop                    End the running test now, and set testing to off.
  run                     Run tests here without the window, when the switch and the schedule allow, until stopped.
  check                   Check this computer can test: the sandbox, your games and a controller to record with.
  log                     The last lines of this computer's log, and of the latest test's.

Reading GitHub (an optional sign-in raises its limit)
  github status           Whether this computer reads GitHub signed in, and its hourly limit.
  github sign-in          Sign in to GitHub with a token read from standard input.
  github sign-out         Sign out of GitHub: forget the token.

Local tests (pull requests you choose, tested on this computer)
  local list              Your local tests: what's waiting, and each pull request's newest result.
  local add               Add pull requests to your local tests, by number or link.
  local remove            Take pull requests off your local tests; their results stay.
  local again             Test a pull request's last tested commit again, keeping the earlier result.
  local report            A pull request's report: the link to post it on, then its text in the project's form.
  local files             The traces to attach to a pull request's report, and the folder they're in.
  local posted            Mark a pull request's report as posted by you (--undo: not posted).
  local follow            Also test every open pull request of these people.
  local unfollow          Stop following these people; pull requests you added by number stay.
  local fixes             Show or set the pull requests merged into both builds as fixes (--none: no fixes).
  local main              The version of main local tests are tested against (--latest: the newest, from the next test).
  local repository        Show or set the project whose pull requests you test.

Your games and the window
  games list              Your games, with each one's test, scenario and folder.
  games add               Add the games in a folder: a game's own folder, or one that holds your games.
  games remove            Take a game off your list; its folder and recordings stay.
  games scenario          Show or choose the scenarios a game is tested in.
  games record            Record a scenario: play from a scenario's starting scene with a controller, for tests to replay.
  games delete-recording  Delete a recorded scenario (never one of this tool's own).
  window                  Open the window (the first-run walkthrough if the config is new).

Options
  --config FILE   the config (default: $TITLE_RUNS_CONFIG, else anyps5-title-runs/config.toml in your config folder)
  --json          print JSON: one object, or one per line for run and games record

Exit codes: 0 done, 1 couldn't (the message says why), 2 the command was written wrong.
No command posts anything or writes to GitHub. You post reports yourself.
`title-runs help COMMAND` says more about each.
```

## This computer

### `title-runs status`

What this computer is doing: the test running, the testing switch, what's next, anything to fix.

```
usage: title-runs status [-h]

What this computer is doing: the test running, the testing switch, what's next, anything to fix.

Shows the test running on this computer (from the window, `title-runs run`, or here), the testing
switch, the next test, and anything that's stopping tests from starting.

options:
  -h, --help  show this help message and exit

Changes: Nothing.
JSON (--json): {"headline", "detail", "kind": "running|setup|off|idle|waiting|ready|error", "testing", "running": {"pr", "head", "title", "step", "progress"} or null, "busy_elsewhere", "next": {"pr", "title", "head"} or null, "notes": [...], "machine", "project", "config", "state"}

Examples:
  title-runs status
  title-runs --json status
```

### `title-runs testing`

Show or set the testing switch: off, schedule or now.

```
usage: title-runs testing [-h] [{off,schedule,now}]

Show or set the testing switch: off, schedule or now.

off: no tests start. schedule: tests run automatically at the times set in the window's When to
test. now: tests run one after another, even outside those times, until you switch back. Switching
doesn't end a running test; `title-runs stop` does. An open window picks up the change within a few
seconds.

positional arguments:
  {off,schedule,now}  off, schedule or now

options:
  -h, --help          show this help message and exit

Changes: This computer's settings (the config file). Only when a mode is given.
JSON (--json): {"testing": "off|schedule|now", "meaning"}

Examples:
  title-runs testing
  title-runs testing now
  title-runs testing off
```

### `title-runs stop`

End the running test now, and set testing to off.

```
usage: title-runs stop [-h]

End the running test now, and set testing to off.

Ends the test running on this computer, whether it was started from the window or `title-runs run`.
Its build or game stops within a few seconds, and the pull request waits to be tested again. Testing
is switched off, so another test doesn't start a minute later.

options:
  -h, --help  show this help message and exit

Changes: This computer's settings (the config file). Testing goes to off.
JSON (--json): {"stopped": PR or null, "testing": "off"}

Examples:
  title-runs stop
```

### `title-runs run`

Run tests here without the window, when the switch and the schedule allow, until stopped.

```
usage: title-runs run [-h] [--once]

Run tests here without the window, when the switch and the schedule allow, until stopped.

Does what the open window does in the background: runs your local tests whenever the testing switch
and the schedule allow. It runs until Ctrl+C, which also ends the running test. --once starts one
test now, ignoring the switch and the schedule, and exits when it's done. Only one test runs on a
computer at a time, so while the window is testing this waits, and the other way round. Nothing runs
until the first-run steps (`title-runs window`) are done.

options:
  -h, --help  show this help message and exit
  --once      one test now, ignoring the switch, then exit

Changes: Builds and runs tests on this computer. Their results stay here.
JSON (--json): one object per line: {"log": text} as it goes, then {"result": text}

Examples:
  title-runs run
  title-runs run --once
  title-runs --json run --once
```

### `title-runs check`

Check this computer can test: the sandbox, your games and a controller to record with.

```
usage: title-runs check [-h]

Check this computer can test: the sandbox, your games and a controller to record with.

Runs the sandbox's self-test (no internet or files of yours inside, risky system calls blocked, the
graphics card available to the game), and says whether anything else is stopping tests from
starting.

options:
  -h, --help  show this help message and exit

Changes: Nothing.
JSON (--json): {"sandbox", "sandbox_ok", "ready", "why", "games": [{"title_id", "name", "test", "chosen", "folder"}], "controller": {"name", "path"} or null}

Examples:
  title-runs check
```

### `title-runs log`

The last lines of this computer's log, and of the latest test's.

```
usage: title-runs log [-h] [--lines LINES]

The last lines of this computer's log, and of the latest test's.

options:
  -h, --help     show this help message and exit
  --lines LINES  how many of each (default 20)

Changes: Nothing.
JSON (--json): {"lines": [...]}

Examples:
  title-runs log
  title-runs log --lines 50
```

## Reading GitHub (an optional sign-in raises its limit)

### `title-runs github status`

Whether this computer reads GitHub signed in, and its hourly limit.

```
usage: title-runs github status [-h]

Whether this computer reads GitHub signed in, and its hourly limit.

Without a sign-in GitHub allows 60 reads an hour, enough for a short list of pull requests; signed
in, 5,000.

options:
  -h, --help  show this help message and exit

Changes: Nothing.
JSON (--json): {"signed_in", "login", "limit", "error"}

Examples:
  title-runs github status
```

### `title-runs github sign-in`

Sign in to GitHub with a token read from standard input.

```
usage: title-runs github sign-in [-h]

Sign in to GitHub with a token read from standard input.

Make the token without any scopes (it can then only read public data), at
https://github.com/settings/tokens/new?description=AnyPS5%20title%20runs&scopes=. It is read from
standard input, so it isn't kept in your shell's history, checked with GitHub, and kept on this
computer readable only by you, sent only to GitHub.

options:
  -h, --help  show this help message and exit

Changes: Keeps the token in the state folder (client/github-token).
JSON (--json): {"signed_in", "login", "limit"}

Examples:
  title-runs github sign-in < token.txt
  title-runs github sign-in   # then paste it and press Enter
```

### `title-runs github sign-out`

Sign out of GitHub: forget the token.

```
usage: title-runs github sign-out [-h]

Sign out of GitHub: forget the token.

options:
  -h, --help  show this help message and exit

Changes: Deletes the token from the state folder.
JSON (--json): {"signed_in": false}

Examples:
  title-runs github sign-out
```

## Local tests (pull requests you choose, tested on this computer)

### `title-runs local list`

Your local tests: what's waiting, and each pull request's newest result.

```
usage: title-runs local list [-h]

Your local tests: what's waiting, and each pull request's newest result.

`title-runs local` on its own does the same. Each pull request shows its newest result, whether its
report has been posted or is out of date, and how many earlier results it has.

options:
  -h, --help  show this help message and exit

Changes: Nothing.
JSON (--json): {"repository", "main", "people", "fixes", "prs": [{"pr", "title", "author", "state": "waiting|tested|failed|not tested", "head", "verdict", "at", "main", "report": "Posted|Out of date: why|Not posted", "stale", "earlier", "removed"}]}

Examples:
  title-runs local
  title-runs --json local list
```

### `title-runs local add`

Add pull requests to your local tests, by number or link.

```
usage: title-runs local add [-h] PR [PR ...]

Add pull requests to your local tests, by number or link.

Each commit the pull request's author pushes is tested once against the project's main, when testing
allows. Commits pushed by anyone else aren't tested. An open window shows them within a minute.

positional arguments:
  PR          numbers or links

options:
  -h, --help  show this help message and exit

Changes: Your local tests list and settings.
JSON (--json): {"added": [PR, ...]}

Examples:
  title-runs local add 4287
  title-runs local add 9287 9289
```

### `title-runs local remove`

Take pull requests off your local tests; their results stay.

```
usage: title-runs local remove [-h] PR [PR ...]

Take pull requests off your local tests; their results stay.

positional arguments:
  PR          numbers or links

options:
  -h, --help  show this help message and exit

Changes: Your local tests list and settings.
JSON (--json): {"removed": [PR, ...]}

Examples:
  title-runs local remove 8566
```

### `title-runs local again`

Test a pull request's last tested commit again, keeping the earlier result.

```
usage: title-runs local again [-h] PR

Test a pull request's last tested commit again, keeping the earlier result.

It waits its turn like any other test; `title-runs run --once` starts it now. It's tested against
the newest main.

positional arguments:
  PR          a pull request's number or link

options:
  -h, --help  show this help message and exit

Changes: Your local tests list.
JSON (--json): {"pr", "head"}

Examples:
  title-runs local again 4287
```

### `title-runs local report`

A pull request's report: the link to post it on, then its text in the project's form.

```
usage: title-runs local report [-h] [--test N] [--text] PR

A pull request's report: the link to post it on, then its text in the project's form.

The newest result's report (--test N for an earlier one), with the traces to attach. Nothing is
posted for you. Post it yourself, then mark it with `title-runs local posted`. --text prints only
the report, ready to paste.

positional arguments:
  PR          a pull request's number or link

options:
  -h, --help  show this help message and exit
  --test N    which result: 1 is the newest (the default), 2 the one before
  --text      only the report's text

Changes: Nothing (makes the folder of traces to attach).
JSON (--json): {"pr", "link", "head", "at", "verdict", "stale", "posted", "text", "traces": [{"name", "path", "size", "fits", "run"}], "folder"}

Examples:
  title-runs local report 4287
  title-runs local report 4287 --text | wl-copy
  title-runs --json local report 4287
```

### `title-runs local files`

The traces to attach to a pull request's report, and the folder they're in.

```
usage: title-runs local files [-h] [--test N] PR

The traces to attach to a pull request's report, and the folder they're in.

Each counted run's trace, named after its run, in one folder you can drag them from into the comment
under Traces. A trace over GitHub's 25 MB limit is listed but can't be attached.

positional arguments:
  PR          a pull request's number or link

options:
  -h, --help  show this help message and exit
  --test N    which result: 1 is the newest (the default), 2 the one before

Changes: Makes the folder on this computer.
JSON (--json): {"pr", "folder", "traces": [{"name", "path", "size", "fits", "run"}]}

Examples:
  title-runs local files 4287
```

### `title-runs local posted`

Mark a pull request's report as posted by you (--undo: not posted).

```
usage: title-runs local posted [-h] [--test N] [--undo] PR

Mark a pull request's report as posted by you (--undo: not posted).

A posted result is never marked out of date. This only records it on this computer; it doesn't post
anything.

positional arguments:
  PR          a pull request's number or link

options:
  -h, --help  show this help message and exit
  --test N    which result: 1 is the newest (the default), 2 the one before
  --undo      mark it not posted

Changes: Your local tests list.
JSON (--json): {"pr", "head", "posted"}

Examples:
  title-runs local posted 4287
  title-runs local posted 4287 --undo
```

### `title-runs local follow`

Also test every open pull request of these people.

```
usage: title-runs local follow [-h] LOGIN [LOGIN ...]

Also test every open pull request of these people.

Every new commit they push to one of their pull requests is tested without you checking it first, so
only follow people whose code you'd run.

positional arguments:
  LOGIN

options:
  -h, --help  show this help message and exit

Changes: Your settings.
JSON (--json): {"people": [...]}

Examples:
  title-runs local follow LOGIN
```

### `title-runs local unfollow`

Stop following these people; pull requests you added by number stay.

```
usage: title-runs local unfollow [-h] LOGIN [LOGIN ...]

Stop following these people; pull requests you added by number stay.

positional arguments:
  LOGIN

options:
  -h, --help  show this help message and exit

Changes: Your settings.
JSON (--json): {"people": [...]}

Examples:
  title-runs local unfollow LOGIN
```

### `title-runs local fixes`

Show or set the pull requests merged into both builds as fixes (--none: no fixes).

```
usage: title-runs local fixes [-h] [--none] [PR ...]

Show or set the pull requests merged into both builds as fixes (--none: no fixes).

For when main can't run your games without them. Any that main already includes are skipped. If one
doesn't merge, or its latest commit wasn't pushed by its author, local tests pause and say why.

positional arguments:
  PR

options:
  -h, --help  show this help message and exit
  --none      no fixes

Changes: Your settings, when given.
JSON (--json): {"fixes": [PR, ...]}

Examples:
  title-runs local fixes
  title-runs local fixes 9730
  title-runs local fixes --none
```

### `title-runs local main`

The version of main local tests are tested against (--latest: the newest, from the next test).

```
usage: title-runs local main [-h] [--latest]

The version of main local tests are tested against (--latest: the newest, from the next test).

Main stays at one version for 12 hours, so the pull requests tested together are compared with the
same main, which is built and warmed up once.

options:
  -h, --help  show this help message and exit
  --latest    use the newest main from the next test on

Changes: With --latest: your local tests list.
JSON (--json): {"main", "pinned": {"main", "base", "fixes", "at"} or null}

Examples:
  title-runs local main
  title-runs local main --latest
```

### `title-runs local repository`

Show or set the project whose pull requests you test.

```
usage: title-runs local repository [-h] [OWNER/NAME]

Show or set the project whose pull requests you test.

positional arguments:
  OWNER/NAME

options:
  -h, --help  show this help message and exit

Changes: Your settings, when given.
JSON (--json): {"repository"}

Examples:
  title-runs local repository
  title-runs local repository boykopovar/AnyPS5
```

## Your games and the window

### `title-runs games list`

Your games, with each one's test, scenario and folder.

```
usage: title-runs games list [-h]

Your games, with each one's test, scenario and folder.

`title-runs games` on its own does the same.

options:
  -h, --help  show this help message and exit

Changes: Nothing.
JSON (--json): {"games": [{"title_id", "name", "version", "test", "chosen", "scenarios", "folder"}]}

Examples:
  title-runs games
```

### `title-runs games add`

Add the games in a folder: a game's own folder, or one that holds your games.

```
usage: title-runs games add [-h] FOLDER

Add the games in a folder: a game's own folder, or one that holds your games.

Looks for games (a folder with eboot.bin and sce_sys/param.json) up to three folders down. A game
with a route in this tool gets a full test; others get a check that they start. Games already set up
are left as they are.

positional arguments:
  FOLDER

options:
  -h, --help  show this help message and exit

Changes: This computer's settings (the config file).
JSON (--json): {"added": [TITLE_ID, ...]}

Examples:
  title-runs games add ~/games
```

### `title-runs games remove`

Take a game off your list; its folder and recordings stay.

```
usage: title-runs games remove [-h] TITLE_ID

Take a game off your list; its folder and recordings stay.

positional arguments:
  TITLE_ID

options:
  -h, --help  show this help message and exit

Changes: This computer's settings (the config file).
JSON (--json): {"removed": TITLE_ID}

Examples:
  title-runs games remove PPSA04263
```

### `title-runs games scenario`

Show or choose the scenarios a game is tested in.

```
usage: title-runs games scenario [-h] TITLE_ID [SCENARIO ...]

Show or choose the scenarios a game is tested in.

A scenario is one specific run of a game, which may or may not load a save first (GTA V's prologue,
or Franklin's house). Each test of the game runs in every scenario given, one after another on the
same builds, and its report has a section for each.

positional arguments:
  TITLE_ID
  SCENARIO

options:
  -h, --help  show this help message and exit

Changes: This computer's settings (the config file). Only when scenarios are given.
JSON (--json): {"title_id", "chosen": [SCENARIO, ...], "scenarios": [{"id", "name", "scene"}]}

Examples:
  title-runs games scenario PPSA04263
  title-runs games scenario PPSA04263 bank-scene walk-to-window-and-look-around
```

### `title-runs games record`

Record a scenario: play from a scenario's starting scene with a controller, for tests to replay.

```
usage: title-runs games record [-h] --from SCENARIO --name NAME --scene SCENE
                               [--seconds SECONDS] [--id ID]
                               TITLE_ID

Record a scenario: play from a scenario's starting scene with a controller, for tests to replay.

Starts the game on the main build (a local test builds it) in the scenario named by --from and goes
to its starting scene on its own, where it may set the camera for a few seconds. Then you take over:
the first second is ignored, and after that everything you do on the controller is recorded for
--seconds (160 to 600; timing starts about 90 s in and lasts up to 60). The new scenario is the one
you started from plus your recording, and every test in it replays the recording from the same
scene. Stopping (title-runs stop, or Stop in the window) ends it without saving.

positional arguments:
  TITLE_ID

options:
  -h, --help         show this help message and exit
  --from SCENARIO    the scenario to start from
  --name NAME        the new scenario's name
  --scene SCENE      what happens in it, for reports (up to 120 characters)
  --seconds SECONDS  how long to record (160 to 600, default 180)
  --id ID            the new scenario's id (default: from its name)

Changes: Starts the game on this computer, and writes the new scenario to the state folder.
JSON (--json): one object per line: {"progress": text} as it goes, then {"recorded": ID, "path"}

Examples:
  title-runs games record PPSA04263 --from franklins-house --name "Out of the house" --scene "Franklin walks out of his house to the road"
```

### `title-runs games delete-recording`

Delete a recorded scenario (never one of this tool's own).

```
usage: title-runs games delete-recording [-h] TITLE_ID SCENARIO

Delete a recorded scenario (never one of this tool's own).

A game that was set to it goes back to its default scenario.

positional arguments:
  TITLE_ID
  SCENARIO

options:
  -h, --help  show this help message and exit

Changes: Deletes the scenario file from the state folder.
JSON (--json): {"deleted": SCENARIO}

Examples:
  title-runs games delete-recording PPSA04263 house-walk
```

### `title-runs window`

Open the window (the first-run walkthrough if the config is new).

```
usage: title-runs window [-h] [--config CONFIG] [--listing LISTING] [--auto]
                         [--dumps DUMPS] [--state STATE]
                         [--screenshots SCREENSHOTS]

The window and the tray. A config that doesn't exist yet is made, and the
first-run walkthrough fills it in; nothing runs before the walkthrough is
done.

options:
  -h, --help            show this help message and exit
  --config CONFIG       the config (default: $TITLE_RUNS_CONFIG, else the
                        user's config folder)
  --listing LISTING     show this pull requests listing instead of the one
                        read from GitHub
  --auto                start with testing on schedule
  --dumps DUMPS         the walkthrough's dumps folder to start from
  --state STATE         a new config: the state directory
  --screenshots SCREENSHOTS
                        render the window's pages to this folder, offscreen,
                        and exit

Changes: Nothing, until you change something in the window.

Examples:
  title-runs window
  title-runs window --config ~/games/anyps5.toml
```
