# Status: paused 2026-10-21 (morning), for Charlie's review

Paused at a safe point: no job, poll or game is running, and every change is committed. Nothing has been posted to
GitHub; the poster has only written to the outbox. There is no remote yet.

## Where it stopped

The last finished step is the end-to-end proof on the laptop, written up in the morning report of 2026-10-21:

- #8104 (head 69ac2e155, merge 7b3f12e95, base d97361bd0): polled, paused on the allowlist, confirmed, built, run as
  a sandboxed A/B on GTA V (four counted runs, no difference beyond the spread), and rendered as a dry-run new
  comment: `~/games/title-runs-state/outbox/8104/20261021-013055-new.md` (written before the UTC date and verdict
  wording fixes; `./title-runs render 8104` gives the current text).
- The simulated second head, on a copy of the state in `~/games/title-runs-demo`: the edited comment with the
  history table is `outbox/8104/20261021-013318-edit.md` there.
- Boot-and-classify: `run_title()` called directly on the #8104 job's main build (stalled at 60 s, rendering at
  240 s), not through a PR job.
- 31 tests pass. SUGGESTIONS.md lists what could go back to #7264.

## State on disk

`~/games/title-runs-state` (about 16 GB: trees, builds, the hard-linked game directory, warm caches for both sides of
the #8104 job, runs). `state.json` has #8104's head as done and #6321 (auto-followed through its Unblocks: line) as
paused. The worktrees `trees/main` and `trees/pr` and the refs `refs/title-runs/pr-8104/*` are in `~/src/AnyPS5`.

## Not done

- The real poster has never called GitHub; it needs the repository, the bot account and its token (README, "The bot
  account").
- No screenshot upload, no scheduler, no cancelling of a running job when a newer head arrives, no sandbox for the
  build, no lookup of the bot's comment by its marker.
- Label follows, maintainer-label trust and a PR without a merge ref are covered by unit tests only.
