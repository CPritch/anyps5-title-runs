# AnyPS5 title runs: results repository

The queue, the testers' claims and results, and the App's comment state for AnyPS5 title runs. See the tool's
DESIGN.md and FORMATS.md (CPritch/anyps5-title-runs). Created from the tool's `results_repo/` template with
`title-runs export-results-repo <main dir> <state dir>`.

Two branches:

- `main` (the default branch; testers' tokens push to it): `claims/`, `results/`, the workflows, this README.
- `state` (only the workflows and the maintainers push to it; protect it): `config.json` (the AnyPS5 repository, the
  maintainers whose labels and `/title-test` commands queue work, each tester's account and machine names),
  `queue.json` and `comments.json`.

The workflows run the tool's code from `vars.TITLE_RUNS_TOOL_REPOSITORY` at `vars.TITLE_RUNS_TOOL_COMMIT`, never code
from this repository, which testers can write to.

Settings this repository needs: the variables `TITLE_RUNS_APP_ID`, `ANYPS5_OWNER`, `ANYPS5_NAME`,
`TITLE_RUNS_TOOL_REPOSITORY`, `TITLE_RUNS_TOOL_COMMIT`; the secrets `TITLE_RUNS_APP_PRIVATE_KEY` (the App's private key)
and, while the tool repository is private, `TITLE_RUNS_TOOL_TOKEN` (read-only access to it); Actions allowed to write
contents; a rule that lets only the workflows and admins push to `state`.
