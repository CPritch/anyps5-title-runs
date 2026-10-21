# The results repository's files and the testers' comments

The results repository is public and maintainer-owned (DESIGN.md). Only its `relay` workflow and the maintainers
write it; testers' clients clone it to read the queue, and report through issues and comments made with their own
sign-in through the App. Every file and comment payload is JSON, UTF-8, with `"format": 1`. `title_runs/formats.py`
reads and checks them on both sides.

```
config.json                       the maintainers' settings
queue.json                        the approved heads to test, and what happened to approvals
registry.json                     registered machines, pending and declined registrations
claims.json                       the claims the workflow has seen (clients read live claims from the job issues)
jobs.json                         each job's issue
results/<job>/<machine>.json      accepted results
comments.json                     the App's comment on each PR and what it last showed
cursors.json                      where the workflow got to, and its last run
.github/workflows/relay.yml, README.md
```

A **job** is one approved commit of one PR: `<pr>-<the first 12 digits of the SHA>`, e.g. `8104-69ac2e155ad0`. Times
are ISO 8601 in UTC (`2026-10-21T12:00:00Z`).

## config.json

```json
{
  "format": 1,
  "repository": "boykopovar/AnyPS5",
  "results_repository": "oneandonlydean/anyps5-title-runs-results",
  "maintainers": ["oneandonlydean", "adriadam10"],
  "label": "title-test",
  "app": {"id": 123456, "client_id": "Iv23li...", "bot": "anyps5-title-runs[bot]"},
  "tool": {"repository": "CPritch/anyps5-title-runs", "commit": "<the commit the workflow runs>"},
  "verdicts": {"threshold_pct": 1, "class_max": 3}
}
```

- `maintainers`: whose `title-test` labels, `/title-test` commands (also with an OWNER, MEMBER or COLLABORATOR
  association) and `approved` labels on registrations count.
- `app`: the App's ID (for the workflow's token), its client ID (the clients' device flow) and its bot account (whose
  own label removals the workflow skips). Public; the private key is the repository's one secret, `APP_PRIVATE_KEY`.
- `tool`: the code the workflow runs, at a pinned commit.
- `verdicts` (optional): `threshold_pct`, the share of main's p50 a difference must exceed on one machine (above 0,
  at most 20, default 1); `class_max`, how many machines a borderline class asks for at most (1 to 20, default 3).
  The workflow, the overview and the clients' scheduling all read them from here.

## queue.json

```json
{
  "format": 1,
  "repository": "boykopovar/AnyPS5",
  "updated": "2026-10-21T12:00:00Z",
  "entries": [
    {
      "job": "8104-69ac2e155ad0", "pr": 8104, "title": "perf(agc): …", "author": "Celegans12",
      "head": "69ac2e155ad018ed1fb9028d2028d15999a8571e",
      "approval": {"by": "CPritch", "at": "2026-10-21T12:00:00Z", "via": "label", "pinned": false},
      "priority": "normal", "titles": [], "hw": [], "machines": 2,
      "queued_by": "CPritch", "queued_at": "2026-10-21T12:00:00Z",
      "earlier": [], "unapproved": [], "issue": 4
    }
  ],
  "stopped": [{"pr": 7922, "by": "CPritch", "at": "…"}],
  "expired": [{"pr": 8104, "head": "69ac…", "job": "8104-69ac2e155ad0", "by": "8118…", "pusher": "Celegans12", "at": "…", "approved_by": "CPritch"}],
  "refused": [{"pr": 8104, "by": "CPritch", "labelled": "…", "head": "8118…", "pushed": "…", "source": "its PR workflow run"}]
}
```

- `head`: the commit a maintainer approved. A label pins the PR's head when the workflow sees the label, if that head
  was pushed before the label (`refused` otherwise); a command's `sha=` pins any commit of the PR. Testers build
  exactly this commit merged onto current main.
- `approval.via`: `label`, `command`, or `carried` (`from`, `reason`): a later head that has the approved head's
  patch-ids, or was pushed by a collaborator who is not the author.
- `unapproved`: heads that were already there when a maintainer pinned an earlier commit with `sha=`; not checked.
- `expired`: approvals a push expired; the App removed the label. `issue`: the job's issue in the results repository.
- `titles`, `hw`, `machines`: as DESIGN.md's `/title-test` options.

## registry.json

```json
{
  "format": 1,
  "machines": {"CPritch/laptop": {"tester": "CPritch", "machine": "laptop", "class": {…}, "titles": ["PPSA04263"], "issue": 2,
                                  "opened": "…", "approved_by": "CPritch", "approved_at": "…", "last_report": "…"}},
  "pending": {"someone/desk": {"tester": "someone", "machine": "desk", "class": {…}, "titles": [], "issue": 7, "opened": "…"}},
  "declined": {}
}
```

`class`: `{"vendor", "os", "gpu", "driver", "os_name"}`; vendor and os are what `hw=` matches; GPU model, driver
branch and OS name give the class results are combined in (DESIGN.md, "Verdicts").

## Testers' comments and issues

Each is one marker line, a sentence for people, and one JSON block:

````
<!-- title-runs claim -->
someone/desk claims 8104-69ac2e155ad0.

```json
{ … }
```
````

| marker | where | payload |
|---|---|---|
| `register` | the body of an issue the tester opens, titled `Machine: <login>/<machine>` | `{"format", "tester", "machine", "class", "titles"}`; `tester` must be the issue's author |
| `claim` | a comment on the job's issue | `{"format", "job", "head", "machine", "tester", "class", "titles", "claimed", "expires", "client"}`: at most 24 hours (the client uses 3) |
| `withdraw` | a comment on the job's issue | `{"job", "machine"}` |
| `result` | a comment on the job's issue, or on the "Runs on testers' own trust" issue for `trust: tester` | the result below |

The workflow uses a comment only when its author has a registered machine of that name; a result only with that
author's claim for the same job and head, made earlier and not expired when the result came. Anything else gets no
reply: it is counted in `cursors.json`'s `ignored` by reason, with the last 20 (time, issue, account, reason,
detail), so a tester's client can show its tester why a comment was not used. A comment body is at most 60,000 characters here (GitHub refuses more than
65,536).

## results/<job>/<machine>.json

Written by the workflow from an accepted `result` comment (with `comment`, the comment's id, and `accepted_at`).
Everything in it may end up in the App's comment, so it is checked field by field (`formats.check_result`): ids
against the path, numbers as numbers, short text without Markdown or HTML markup characters (`< > | backtick`, line
breaks), summary lines as single lines of at most 6000 characters.

```json
{
  "format": 1, "job": "8104-69ac2e155ad0", "pr": 8104, "head": "69ac2e155ad0…", "base": "d97361bd0df0…", "merge": "f0a2a25b4…",
  "machine": "laptop", "tester": "CPritch", "class": {…},
  "machine_line": "NVIDIA GeForce RTX 5060 Laptop GPU, NVIDIA 615.71.09, Linux 7.2.8-zen1-2-zen",
  "trust": "queue", "sandbox": "bwrap", "status": "done", "started": "…", "finished": "…",
  "titles": {
    "PPSA04263": {
      "name": "Grand Theft Auto V", "version": "01.010.002", "scene": "Story Mode, Resume Story: the loaded scene",
      "outcome": {"A": "rendering", "B": "rendering"},
      "sides": {"A": {"p50": [78.0, 78.0], "p90": […], "p99": […], "gpu": […]}, "B": {"p50": [77.6, 77.7], …}},
      "verdict": {"verdict": "no difference", …},
      "summary_lines": {"A": ["{…}"], "B": ["{…}"]}
    }
  }
}
```

- `base`: the main commit the client merged `head` onto; `merge`: the local merge it built.
- The workflow recomputes the verdict from `sides` (verdict.py); `verdict` is the client's own reading, kept for the
  record.

## claims.json, jobs.json, comments.json, cursors.json

The workflow's own bookkeeping: `claims.json` `{job: {machine: claim + comment}}`; `jobs.json` `{job: {"issue", "pr",
"head", "state", "reason"}}`; `comments.json` `{"prs": {pr: {"comment_id", "posts": [{"action", "at", "reason",
"heads", "body_sha256"}]}}}` (a new comment when, for a machine and title, an outcome class changed or the verdict
changed to faster or slower; otherwise an edit); `cursors.json` the last AnyPS5 event and comment seen, the last
results-repository comment seen, the overview and tester-trust issue numbers, `last_run`, and `ignored`:
`{"counts": {reason: n}, "last", "recent": [...], "seen": [...]}` (reasons: `unregistered`, `chatter`, `unreadable`,
`elsewhere`, `claim`, `result`, `registration`, `label`; `seen` keeps labels and open issues counted once).
