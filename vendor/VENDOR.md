# Vendored code

Unchanged copies. Do not edit them here: changes go to their sources, and a new copy replaces the old one
with its commit named below.

| path | source | commit |
|---|---|---|
| title_run/tools/title_run.py, titles.json, unwrap_self.py, package_release.py | boykopovar/AnyPS5 PR #7264 (LeandroLP23, "feat(tools): run titles repeatably and report their outcome"), the PR head's `tools/` | c2dce8dd3 |
| gtav_harness/frame_state.py, steady.py, capture.py | CPritch/gtav-harness `tools/` | ab8b91c |

`title_run.py` imports `unwrap_self` and `package_release` from the directory next to it, so they come from the same
PR head (they are main's files at its base). `performance_compare.py`, `trace_digest.py` and `pad_input.py` are not
vendored: each job runs them from its own checkout of main's base commit, so they always match the build.
