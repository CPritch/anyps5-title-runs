# The title-runs command line

Made by `title-runs help --markdown` from the commands themselves (title_runs/cli.py); a test checks it is current.

```
title-runs: test AnyPS5 pull requests on your own games and hardware, against main.

Usage: title-runs [--config FILE] [--json] COMMAND [ARGS]

This computer
  status               What this computer is doing: the test running, the testing switch, what's next, anything to fix.
  testing              Show or set the testing switch: off, schedule or now.
  stop                 End the running test now, and set testing to off.
  run                  Run tests here without the window, as the switch and the schedule allow, until stopped.
  check                Check this computer can test: the sandbox, your games and the sign-in.
  log                  The last lines of this computer's log, and of the latest test's.

Local tests: pull requests you pick, tested on this computer. Nothing is posted.
  local list           Your local tests: what's waiting, and each pull request's newest result.
  local add            Add pull requests to your local tests, by number or link.
  local remove         Take pull requests off your local tests; their results stay.
  local again          Test a pull request's latest tested head again; the earlier result stays.
  local report         A pull request's report: the link to post it on, then its text in the project's form.
  local files          The traces to attach to a pull request's report, and the folder they're in.
  local posted         Mark a pull request's report as posted by you (--undo: not posted).
  local follow         Also test every open pull request of these people.
  local unfollow       Stop following these people; pull requests you added by number stay.
  local fixes          Show or set the fixes merged onto main for both sides (--none: no fixes).
  local main           What local tests are measured against now (--latest: main afresh at the next test).
  local repository     Show or set the project whose pull requests your local tests come from.

The queue: tests maintainers ask for, kept in a results repository
  queue list           The queue: the tests maintainers asked for, what each still wants, and what this machine takes next.
  queue add            Ask for a test of a pull request (maintainers).  [writes to GitHub]
  results              A pull request's results: each machine's, and the verdict per kind of machine.
  machines list        The registered machines, when each last reported, and those waiting for approval.
  machines approve     Approve a machine waiting for approval (maintainers).  [writes to GitHub]
  machines decline     Decline a machine waiting for approval (maintainers).  [writes to GitHub]

Your account, your games and the window
  sign-in              Sign in with GitHub: shows a code to type at github.com/login/device, then waits.
  sign-out             Forget the sign-in on this computer.
  register             Register this machine with the results repository, for a maintainer to approve.  [writes to GitHub]
  use                  Switch to another results repository (the testing link you were given).
  games list           Your games: each one's test, scenario and folder.
  games scenario       Show or choose the scenario a game is timed in.
  window               Open the window (the first-run walkthrough if the config is new).

Setting up testing for a project (maintainers)
  app                  Make the GitHub App for a project's testing, from its manifest.
  export-results-repo  Make a project's results repository, ready to push.

Run by GitHub, and for development
  relay                The results repository's workflow: what GitHub Actions runs every 5 minutes.  [writes to GitHub]
  standin              The local stand-in for GitHub and the results repository, for development.

Options
  --config FILE   the config (default: $TITLE_RUNS_CONFIG, else anyps5-title-runs/config.toml in your config folder)
  --json          print JSON: one object, or one per line for run and sign-in

Exit codes: 0 done, 1 couldn't (the message says why), 2 the command was written wrong.
Commands marked [writes to GitHub] do so as you (relay: as the App); nothing else posts anything.
`title-runs help COMMAND` says more about each.
```

## This computer

### `title-runs status`

What this computer is doing: the test running, the testing switch, what's next, anything to fix.

```
usage: title-runs status [-h] [--fetch]

What this computer is doing: the test running, the testing switch, what's next, anything to fix.

Shows the test running on this computer (in the window, `title-runs run`, or here), the testing
switch and what it means now, the next test, and anything that keeps tests from starting. The
results repository is read as last fetched; --fetch updates it first.

options:
  -h, --help  show this help message and exit
  --fetch     fetch the results repository first

Changes: Nothing (--fetch updates this computer's copy of the results repository).
JSON (--json): {"headline", "detail", "kind": "running|setup|off|idle|waiting|ready|error", "testing", "running": {"pr", "head", "title", "step", "progress", "local"} or null, "busy_elsewhere", "next": {"pr", "title", "head", "local"} or null, "notes": [...], "signed_in", "machine", "results_repository", "local_only", "config", "state"}

Examples:
  title-runs status
  title-runs --json status
```

### `title-runs testing`

Show or set the testing switch: off, schedule or now.

```
usage: title-runs testing [-h] [{off,schedule,now}]

Show or set the testing switch: off, schedule or now.

off: no test starts. schedule: tests start by themselves at the times set in the window's When to
test. now: one test after another, whatever the time, until you switch back. A running test goes on
either way; `title-runs stop` ends it. An open window follows within a few seconds.

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

Ends the test running on this computer, wherever it was started (the window, `title-runs run`): its
build or game ends within a few seconds, and nothing is sent. Testing goes to off, so another test
doesn't start a minute later.

options:
  -h, --help  show this help message and exit

Changes: This computer's settings (the config file). Testing goes to off.
JSON (--json): {"stopped": PR or null, "testing": "off"}

Examples:
  title-runs stop
```

### `title-runs run`

Run tests here without the window, as the switch and the schedule allow, until stopped.

```
usage: title-runs run [-h] [--once]

Run tests here without the window, as the switch and the schedule allow, until stopped.

Does what the open window does in the background: the queue's tests first (when this machine is
registered), then local tests, whenever the testing switch and the schedule let one start. It runs
until Ctrl+C, which also ends the test running. --once: start one test now, whatever the switch and
the schedule say, and exit when it's done. One test runs on a computer at a time: while the window
is testing, this waits, and the other way round. Nothing runs before the first-run walkthrough
(`title-runs window`) is done.

options:
  -h, --help  show this help message and exit
  --once      one test now, whatever the switch says, then exit

Changes: Builds and runs tests on this computer. A queued test's result goes to the results repository as you; a local test's stays here.
JSON (--json): one object per line: {"log": text} as it goes, then {"result": text}

Examples:
  title-runs run
  title-runs run --once
  title-runs --json run --once
```

### `title-runs check`

Check this computer can test: the sandbox, your games and the sign-in.

```
usage: title-runs check [-h]

Check this computer can test: the sandbox, your games and the sign-in.

Runs the sandbox's self-test (no internet and none of your files inside; the graphics card available
to the game) and says whether anything else keeps tests from starting.

options:
  -h, --help  show this help message and exit

Changes: Nothing.
JSON (--json): {"sandbox", "sandbox_ok", "ready", "why", "games": [{"title_id", "name", "test", "scenario", "folder"}], "signed_in"}

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

## Local tests: pull requests you pick, tested on this computer. Nothing is posted.

### `title-runs local list`

Your local tests: what's waiting, and each pull request's newest result.

```
usage: title-runs local list [-h]

Your local tests: what's waiting, and each pull request's newest result.

`title-runs local` alone does the same. Each pull request shows its newest result, whether its
report is posted or stale, and how many earlier results it has.

options:
  -h, --help  show this help message and exit

Changes: Nothing.
JSON (--json): {"repository", "main", "people", "fixes", "prs": [{"pr", "title", "author", "state": "waiting|tested|failed|not tested", "head", "verdict", "at", "main", "report": "Posted|Stale: why|Not posted", "stale", "earlier", "removed"}]}

Examples:
  title-runs local
  title-runs --json local list
```

### `title-runs local add`

Add pull requests to your local tests, by number or link.

```
usage: title-runs local add [-h] PR [PR ...]

Add pull requests to your local tests, by number or link.

Each head its author pushes is tested once, against the project's main, when testing allows. A head
someone else pushed isn't tested. An open window shows them within a minute.

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

Test a pull request's latest tested head again; the earlier result stays.

```
usage: title-runs local again [-h] PR

Test a pull request's latest tested head again; the earlier result stays.

It waits for testing like any other; `title-runs run --once` starts it now. Main is pinned afresh
for it.

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
posted: you post it yourself, then mark it with `title-runs local posted`. --text prints only the
report, to paste.

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

Each counted run's trace, named for its run, linked into one folder to drag into the comment under
Traces. A trace over GitHub's 25 MB is listed but can't be attached.

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

A posted result never goes stale. This only records it here; it doesn't post anything.

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

Show or set the fixes merged onto main for both sides (--none: no fixes).

```
usage: title-runs local fixes [-h] [--none] [PR ...]

Show or set the fixes merged onto main for both sides (--none: no fixes).

For a main that can't run your games without them. A fix main already has is left out; one that
doesn't merge, or whose head its author didn't push, holds local tests and says why.

positional arguments:
  PR

options:
  -h, --help  show this help message and exit
  --none      carry no fixes

Changes: Your settings, when given.
JSON (--json): {"fixes": [PR, ...]}

Examples:
  title-runs local fixes
  title-runs local fixes 9730
  title-runs local fixes --none
```

### `title-runs local main`

What local tests are measured against now (--latest: main afresh at the next test).

```
usage: title-runs local main [-h] [--latest]

What local tests are measured against now (--latest: main afresh at the next test).

Main is pinned for 12 hours, so the pull requests tested together are measured against the same
main, and it's built and warmed up once.

options:
  -h, --help  show this help message and exit
  --latest    take main as it is at the next test

Changes: With --latest: your local tests list.
JSON (--json): {"main", "pinned": {"main", "base", "fixes", "at"} or null}

Examples:
  title-runs local main
  title-runs local main --latest
```

### `title-runs local repository`

Show or set the project whose pull requests your local tests come from.

```
usage: title-runs local repository [-h] [OWNER/NAME]

Show or set the project whose pull requests your local tests come from.

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

## The queue: tests maintainers ask for, kept in a results repository

### `title-runs queue list`

The queue: the tests maintainers asked for, what each still wants, and what this machine takes next.

```
usage: title-runs queue list [-h] [--fetch]

The queue: the tests maintainers asked for, what each still wants, and what this machine takes next.

`title-runs queue` alone does the same. Read as the workflow last left it; --fetch updates this
computer's copy first.

options:
  -h, --help  show this help message and exit
  --fetch     fetch the results repository first

Changes: Nothing (--fetch updates this computer's copy of the results repository).
JSON (--json): {"results_repository", "project", "updated", "entries": [{"pr", "title", "head", "priority", "approved_by", "reported", "combined": [...], "wanted", "running_on": [...], "for_this_machine", "why"}]}

Examples:
  title-runs queue
  title-runs --json queue --fetch
```

### `title-runs queue add`

Ask for a test of a pull request (maintainers).

```
usage: title-runs queue add [-h] PR

Ask for a test of a pull request (maintainers).

Adds the queue's label on the pull request, as you, the same as adding it on GitHub. The workflow
takes the head that was pushed before the label on its next run; a later push expires it.

positional arguments:
  PR          a pull request's number or link

options:
  -h, --help  show this help message and exit

Changes: Writes to GitHub as you: the label on the pull request.
JSON (--json): {"queued": PR}

Examples:
  title-runs queue add 9289
```

### `title-runs results`

A pull request's results: each machine's, and the verdict per kind of machine.

```
usage: title-runs results [-h] [--fetch] PR

A pull request's results: each machine's, and the verdict per kind of machine.

Every head of the pull request that has results, oldest first. Machines are combined only with
machines of the same graphics card, driver and system (and scenario).

positional arguments:
  PR          a pull request's number or link

options:
  -h, --help  show this help message and exit
  --fetch     fetch the results repository first

Changes: Nothing (--fetch updates this computer's copy of the results repository).
JSON (--json): {"pr", "heads": [{"head", "job", "machines": [{"machine", "tester", "title_id", "verdict", "diff_ms", "diff_pct", "hardware", "finished"}], "combined": [...]}]}

Examples:
  title-runs results 8104
  title-runs --json results 8104 --fetch
```

### `title-runs machines list`

The registered machines, when each last reported, and those waiting for approval.

```
usage: title-runs machines list [-h] [--fetch]

The registered machines, when each last reported, and those waiting for approval.

`title-runs machines` alone does the same.

options:
  -h, --help  show this help message and exit
  --fetch     fetch the results repository first

Changes: Nothing (--fetch updates this computer's copy of the results repository).
JSON (--json): {"results_repository", "machines": [{"tester", "machine", "hardware", "titles", "approved_by", "last_report"}], "pending": [{"tester", "machine", "issue", "hardware"}]}

Examples:
  title-runs machines
```

### `title-runs machines approve`

Approve a machine waiting for approval (maintainers).

```
usage: title-runs machines approve [-h] ISSUE

Approve a machine waiting for approval (maintainers).

Adds the label approved to its registration issue, as you; the workflow records it on its next run.

positional arguments:
  ISSUE       the registration issue's number (title-runs machines)

options:
  -h, --help  show this help message and exit

Changes: Writes to GitHub as you: the label on the registration issue.
JSON (--json): {"issue", "label"}

Examples:
  title-runs machines approve 12
```

### `title-runs machines decline`

Decline a machine waiting for approval (maintainers).

```
usage: title-runs machines decline [-h] ISSUE

Decline a machine waiting for approval (maintainers).

positional arguments:
  ISSUE       the registration issue's number (title-runs machines)

options:
  -h, --help  show this help message and exit

Changes: Writes to GitHub as you: the label on the registration issue.
JSON (--json): {"issue", "label"}

Examples:
  title-runs machines decline 12
```

## Your account, your games and the window

### `title-runs sign-in`

Sign in with GitHub: shows a code to type at github.com/login/device, then waits.

```
usage: title-runs sign-in [-h]

Sign in with GitHub: shows a code to type at github.com/login/device, then waits.

The sign-in reads pull requests for local tests and the queue; for the queue it also sends your
machine's registration and results as you. A config for local tests only posts nothing with it.

options:
  -h, --help  show this help message and exit

Changes: Keeps the sign-in on this computer.
JSON (--json): one object per line: {"verification_uri", "user_code"}, then {"signed_in": LOGIN}

Examples:
  title-runs sign-in
```

### `title-runs sign-out`

Forget the sign-in on this computer.

```
usage: title-runs sign-out [-h]

Forget the sign-in on this computer.

options:
  -h, --help  show this help message and exit

Changes: Removes the sign-in from this computer.
JSON (--json): {"signed_in": null}

Examples:
  title-runs sign-out
```

### `title-runs register`

Register this machine with the results repository, for a maintainer to approve.

```
usage: title-runs register [-h] [--name NAME]

Register this machine with the results repository, for a maintainer to approve.

Until a maintainer approves it, the machine takes no queued tests. Local tests don't need it.

options:
  -h, --help   show this help message and exit
  --name NAME  this machine's name: 1 to 32 letters, digits and hyphens

Changes: Writes to GitHub as you: a public registration issue with this machine's name, graphics card, driver and system.
JSON (--json): {"registration": "pending|approved|declined", "issue"}

Examples:
  title-runs register
  title-runs register --name my-desktop
```

### `title-runs use`

Switch to another results repository (the testing link you were given).

```
usage: title-runs use [-h] OWNER/NAME

Switch to another results repository (the testing link you were given).

The registration is per repository, and the sign-in is kept only when the new one names the same
App.

positional arguments:
  OWNER/NAME  the results repository, or its link

options:
  -h, --help  show this help message and exit

Changes: This computer's settings (the config file).
JSON (--json): {"results_repository"}

Examples:
  title-runs use CPritch/anyps5-title-runs-results
```

### `title-runs games list`

Your games: each one's test, scenario and folder.

```
usage: title-runs games list [-h]

Your games: each one's test, scenario and folder.

`title-runs games` alone does the same.

options:
  -h, --help  show this help message and exit

Changes: Nothing.
JSON (--json): {"games": [{"title_id", "name", "version", "test", "scenario", "scenarios", "folder"}]}

Examples:
  title-runs games
```

### `title-runs games scenario`

Show or choose the scenario a game is timed in.

```
usage: title-runs games scenario [-h] TITLE_ID [SCENARIO]

Show or choose the scenario a game is timed in.

A scenario is one specific run of a game, which may or may not load a save first (GTA V's prologue,
or Franklin's house). The next tests of the game run in it.

positional arguments:
  TITLE_ID
  SCENARIO

options:
  -h, --help  show this help message and exit

Changes: This computer's settings (the config file). Only when a scenario is given.
JSON (--json): {"title_id", "scenario", "scenarios": [{"id", "name", "scene"}]}

Examples:
  title-runs games scenario PPSA04263
  title-runs games scenario PPSA04263 franklins-house
```

### `title-runs window`

Open the window (the first-run walkthrough if the config is new).

```
usage: title-runs window [-h] [--config CONFIG] [--listing LISTING] [--auto]
                         [--dumps DUMPS] [--results RESULTS] [--github GITHUB]
                         [--state STATE] [--screenshots SCREENSHOTS]
                         [--no-sync]

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
  --results RESULTS     a new config: the results repository, OWNER/NAME or a
                        URL
  --github GITHUB       a new config: "github", or "standin:<github.json>" for
                        the local stand-in
  --state STATE         a new config: the state directory
  --screenshots SCREENSHOTS
                        render the window's pages to this folder, offscreen,
                        and exit
  --no-sync             --screenshots: read the results checkout as it is (a
                        client may be using it)

Changes: Nothing by itself; the window changes what you change in it.

Examples:
  title-runs window
  title-runs window --config ~/games/anyps5.toml
```

## Setting up testing for a project (maintainers)

### `title-runs app`

Make the GitHub App for a project's testing, from its manifest.

```
usage: title-runs app [-h] --results-repo RESULTS_REPO [--name NAME]
                      [--out OUT] [--port PORT] [--no-browser]
                      {manifest,create}

The GitHub App, from a manifest (title_runs/app.py). The project, the results
repository and this tool come from the results repository's config.json.

positional arguments:
  {manifest,create}     manifest: print it; create: make the App on GitHub
                        (you press Create there)

options:
  -h, --help            show this help message and exit
  --results-repo RESULTS_REPO
                        the exported results repository (its config.json)
  --name NAME
  --out OUT             create: where app.json and the private key go (keep it
                        out of every repository)
  --port PORT
  --no-browser

Changes: Creates a GitHub App on your account when you press Create on GitHub.

Examples:
  title-runs app manifest --results-repo RESULTS
  title-runs app create --results-repo RESULTS --out ~/secrets/title-runs
```

### `title-runs export-results-repo`

Make a project's results repository, ready to push.

```
usage: title-runs export-results-repo [-h] [--maintainers MAINTAINERS]
                                      [--app APP] [--tool TOOL]
                                      [--tool-commit TOOL_COMMIT] [--git]
                                      dir [anyps5] [results]

Make a results repository from results_repo/: its config.json, workflow and
README, ready to push to a new public repository with --git.

positional arguments:
  dir                   where to make it
  anyps5                the project, OWNER/NAME
  results               the results repository it becomes, OWNER/NAME

options:
  -h, --help            show this help message and exit
  --maintainers MAINTAINERS
                        comma-separated logins
  --app APP             app.json from 'title-runs app create'
  --tool TOOL           this tool's repository, OWNER/NAME
  --tool-commit TOOL_COMMIT
                        the commit the workflow runs (default: this checkout's
                        HEAD, which must be pushed)
  --git                 make DIR a git repository with one commit, ready to
                        push

Changes: Writes the folder you name.

Examples:
  title-runs export-results-repo RESULTS boykopovar/AnyPS5 OWNER/RESULTS --git
```

## Run by GitHub, and for development

### `title-runs relay`

The results repository's workflow: what GitHub Actions runs every 5 minutes.

```
usage: title-runs relay [-h] COMMAND ...

The results repository's workflow (relay.yml), which GitHub Actions runs every
5 minutes: it reads the project's labels, commands and pushes and the testers'
comments, and writes the queue, the App's comments and the results
repository's files.

positional arguments:
  COMMAND
    poll      one run of the workflow

options:
  -h, --help  show this help message and exit

Changes: Writes to GitHub as the App: labels, comments and the results repository's files (nothing with --dry-run).

Examples:
  title-runs relay poll --dry-run
```

### `title-runs standin`

The local stand-in for GitHub and the results repository, for development.

```
usage: title-runs standin [-h]
                          {tick,label,unlabel,command,push,approve,decline,codes,authorize} ...

The local stand-in for GitHub, the results repository and its workflow, on one
machine, for development (title_runs/standin.py).

positional arguments:
  {tick,label,unlabel,command,push,approve,decline,codes,authorize}
    tick                run the workflow once
    label               add the queue's label on PR as --by
    unlabel             take it off
    command             comment BODY on PR as --by (a /title-test command)
    push                push HEAD to PR as --by
    approve             approve registration ISSUE as --by
    decline             decline registration ISSUE as --by
    codes               the device codes waiting to be entered
    authorize           enter CODE as --as

options:
  -h, --help            show this help message and exit

Changes: Writes the stand-in's folder.

Examples:
  title-runs standin tick --root STANDIN
```
