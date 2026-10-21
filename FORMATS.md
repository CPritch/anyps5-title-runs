# The results repository's files

The results repository (maintainer-owned; see DESIGN.md) holds the queue, the testers' claims and results, and the
state of the App's comments, on two branches. Every file is JSON, UTF-8, with `"format": 1`. `title_runs/formats.py`
reads and checks them on both sides: the client and the workflows.

```
branch state (only the workflows and the maintainers push to it)
  config.json                       maintainers' settings (maintainers, testers, the AnyPS5 repository)
  queue.json                        written by the queue workflow
  comments.json                     written by the queue and publish workflows
branch main (the default; testers' tokens push to it)
  claims/<job>/<machine>.json       written by a tester's client
  results/<job>/<machine>.json      written by a tester's client
  .github/workflows/queue.yml, publish.yml, README.md
```

A tester's token can write to the whole repository, so what decides what runs and what is posted (the queue, the
configuration, the record of accepted results) lives on `state`, which a repository rule must protect; the workflows
never read those files from `main`. No code lives in the results repository either: the workflows run the tool from
its own repository at a commit pinned in a repository variable.

A **job** is one approved commit of one PR: `<pr>-<the first 12 digits of the SHA>`, e.g. `8104-69ac2e155ad0`.

Times are ISO 8601 with a zone, written in UTC (`2026-10-21T12:00:00Z`).

## config.json

Written by the maintainers by hand.

```json
{
  "format": 1,
  "repository": "boykopovar/AnyPS5",
  "maintainers": ["oneandonlydean", "adriadam10"],
  "label": "title-test",
  "testers": {"CPritch": {"machines": ["laptop", "desktop"]}}
}
```

- `maintainers`: the accounts whose labels and `/title-test` commands queue work. A command also needs an
  `author_association` of OWNER, MEMBER or COLLABORATOR on AnyPS5.
- `testers`: the account each tester's token belongs to, and the machine names it may write claims and results for.
  The publish workflow refuses a result pushed by another account.

## queue.json

Written only by the queue workflow, from AnyPS5's label and comment events (and its own refresh of each queued PR's
head).

```json
{
  "format": 1,
  "repository": "boykopovar/AnyPS5",
  "updated": "2026-10-21T12:00:00Z",
  "entries": [
    {
      "job": "8104-69ac2e155ad0",
      "pr": 8104,
      "title": "perf(agc): stage the written elements of address-based compute builds in device memory",
      "author": "Celegans12",
      "head": "69ac2e155ad018ed1fb9028d2028d15999a8571e",
      "approval": {"by": "CPritch", "at": "2026-10-21T12:00:00Z", "via": "label", "pinned": false},
      "priority": "normal",
      "titles": [],
      "hw": [],
      "machines": 2,
      "queued_by": "CPritch",
      "queued_at": "2026-10-21T12:00:00Z",
      "earlier": [],
      "unapproved": []
    }
  ],
  "stopped": [{"pr": 7922, "by": "CPritch", "at": "2026-10-21T13:00:00Z"}]
}
```

- `head` is the commit a maintainer approved, taken from the event itself: the PR's head SHA in the label event's
  payload, or a command's `sha=`. Testers build exactly this commit merged onto current main; never
  `refs/pull/N/merge` or the branch's head.
- `approval.via`: `label`, `command`, or `carried` (a later head taken over without a maintainer, below), with
  `from` (the earlier approved SHA) and `reason`. `pinned` is true when the command named the SHA (`sha=`).
- `unapproved`: pushes after the approval that were not carried over (`{"sha", "by", "at"}`, oldest first). They are
  "not checked" until a maintainer approves one; the entry keeps the approved `head` meanwhile.
- A push is carried over (the entry moves to the new head, `approval.via` = `carried`) only when
  - the new head's own commits (from its merge base with main) have the same patch-ids, in order, as the approved
    head's: a rebase that changed nothing the maintainer looked at; or
  - the push was made by an account whose association with AnyPS5 is OWNER, MEMBER or COLLABORATOR and that is not
    the PR's author.
- `earlier`: approved heads this entry has moved on from, oldest first; their results stay in the comment's history.
- `titles`: title IDs wanted; empty means any. `hw`: hardware tokens wanted (`amd`, `intel`, `nvidia`, `linux`,
  `windows`, or a GPU family that appears in the GPU's name, like `rtx 40`); empty means any. `machines`: how many
  distinct machines should report this head (default 2).
- `stopped`: PRs taken off the queue with `/title-test stop`.

## claims/<job>/<machine>.json

Written by a tester's client before it fetches or builds anything.

```json
{
  "format": 1,
  "job": "8104-69ac2e155ad0",
  "head": "69ac2e155ad018ed1fb9028d2028d15999a8571e",
  "machine": "laptop",
  "tester": "CPritch",
  "class": {"vendor": "nvidia", "os": "linux", "gpu": "NVIDIA GeForce RTX 5060 Laptop GPU"},
  "titles": ["PPSA04263"],
  "claimed": "2026-10-21T12:05:00Z",
  "expires": "2026-10-21T15:05:00Z",
  "client": "anyps5-title-runs 0.2"
}
```

- `expires`: at most 24 hours after `claimed`; the client uses 3 hours and renews a claim that is still running.
  An expired claim counts for nothing (the scheduler ignores it, and the publish workflow refuses a result pushed
  after its claim expired).
- `class` is what the scheduler matches `hw=` against and groups coverage by (`vendor/os`): two machines of one
  class do not hold claims on one job at once.

## results/<job>/<machine>.json

Written by a tester's client when the job ends (done, failed, or superseded). Everything in it may end up in the
App's comment, so the publish workflow checks every field (`formats.check_result`): ids against the path, numbers as
numbers, short text without Markdown or HTML markup characters (`< > | backtick`, line breaks), summary lines as
single lines of at most 6000 characters.

```json
{
  "format": 1,
  "job": "8104-69ac2e155ad0",
  "pr": 8104,
  "head": "69ac2e155ad018ed1fb9028d2028d15999a8571e",
  "base": "d97361bd0df0…",
  "merge": "1a2b3c4d…",
  "machine": "laptop",
  "tester": "CPritch",
  "class": {"vendor": "nvidia", "os": "linux", "gpu": "NVIDIA GeForce RTX 5060 Laptop GPU"},
  "machine_line": "NVIDIA GeForce RTX 5060 Laptop GPU, NVIDIA 615.71.09, Linux 7.2.8-zen1-2-zen",
  "trust": "queue",
  "sandbox": "bwrap",
  "status": "done",
  "started": "2026-10-21T12:05:00Z",
  "finished": "2026-10-21T12:55:00Z",
  "titles": {
    "PPSA04263": {
      "name": "Grand Theft Auto V", "version": "01.010.002", "scene": "Story Mode, Resume Story: the loaded scene",
      "outcome": {"A": "rendering", "B": "rendering"},
      "verdict": {"verdict": "no difference beyond the spread", "diff": -0.33, "diff_pct": -0.43, "spread": 0.39, "gpu_diff": 0.07},
      "sides": {"A": {"p50": [78.2, 77.9], "p90": [87.6, 89.1], "p99": [108.9, 114.4], "gpu": [63.0, 62.6]},
                "B": {"p50": [77.9, 77.5], "p90": [87.9, 88.0], "p99": [109.5, 105.9], "gpu": [63.0, 62.7]}},
      "summary_lines": {"A": ["{\"commit\":\"d97361bd0df0\",…}"], "B": ["…"]},
      "not_counted": []
    }
  }
}
```

- `base`: the main commit the client merged `head` onto; `merge`: the local merge commit it built (its SHA differs
  between machines; only `head` and `base` identify what was built).
- Side A is main at `base`, side B is the merge. `outcome` per side is #7264's class (`rendering`, `crashed`,
  `exited`, `stalled`, `blank`, `relink-failed`), with a short reason.
- `verdict`: `faster`, `slower`, `no difference beyond the spread` or `not enough counted runs`
  (`protocol.verdict`); a difference counts when it is larger than both sides' spreads.
- `trust`: `queue` (a maintainer-approved head) or `tester` (the tester ran a head nobody approved, after the trust
  dialog). The comment lists the two separately.

## comments.json

Written by the queue and publish workflows: the App's comment on each PR, and what it last said.

```json
{
  "format": 1,
  "prs": {
    "8104": {"comment_id": 123456, "posts": [{"action": "new", "at": "2026-10-21T12:00:10Z", "reason": "the first comment on this PR",
                                              "heads": {}, "body_sha256": "…"}]}
  },
  "accepted": {
    "results/8104-69ac2e155ad0/laptop.json": {"pr": 8104, "sha256": "…", "at": "2026-10-21T12:56:00Z", "by": "CPritch"}
  }
}
```

- `accepted`: the result files the publish workflow accepted, with the SHA-256 of the content it checked. The
  comment shows only these; a file changed later is left out until a new push of it is accepted.

- One comment per PR. It is edited as heads and machines report; a new comment is posted instead when, for a machine
  and title, an outcome class changed or the verdict changed to faster or slower (edits notify nobody). `posts`
  records each post with the state it showed (`heads`: per approved head, per machine and title, the outcome classes
  and the verdict), which the next post is compared with.
