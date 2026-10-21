# End to end on the laptop with the stand-in, 2026-10-21

The stand-in (title_runs/standin.py) played GitHub and the results repository; the laptop's client did the rest.
Nothing went to GitHub.

| step | what happened | outbox |
|---|---|---|
| 1 | a fixture label on #8104 by CPritch (maintainer): queued 69ac2e155, the head in the label event | 001 new: "Queued `69ac2e155` for title runs" |
| 2 | the laptop claimed 8104-69ac2e155ad0, merged 69ac2e155 onto main d97361bd0 locally (f0a2a25b4), built both in the build sandbox, ran the A/B on GTA V in the title sandbox (4 counted runs), pushed results/8104-69ac2e155ad0/laptop.json; the publish hook accepted it | 002 edit: the laptop's row, "faster" (p50 -0.34 ms, spread 0.13 ms) |
| 3 | the author pushed 8118a04e4 (a stand-in second head: 69ac2e155 plus one doc file, made locally) | 003 edit: "`8118a04e4` pushed after approval by @Celegans12: **not checked**" |
| 4 | CPritch commented `/title-test sha=8118a04e4` | 004 react +1; 005 edit: queued 8118a04e4 |
| 5 | the laptop claimed 8104-8118a04e4ff4, merged it onto d97361bd0 (0b6c16b87), built, ran, pushed; the publish hook accepted it | 006 edit: the new head's row, "no difference beyond the spread", 69ac2e155 under Earlier heads |

workflows.log is the stand-in's log of both workflows (the hook's JSON reports left out).
