# End to end, round 3: the laptop against the stand-in (2026-10-21, 15:30–15:50 UTC)

`drive.py` ran each step; `steps.log` has every line it wrote. The stand-in played GitHub, the public results
repository and its relay workflow (`~/games/title-runs-r3/standin`). Each "workflow run" below is one `tick()`, the
run GitHub would start every 5 minutes. Nothing went to GitHub.

People in the stand-in:
- **CPritch** is the maintainer (admin on both repositories).
- **Celegans12** is #8104's author, with read permission only.
- **standin-tester**, **standin-tester-2** and **standin-tester-3** are testers with no permissions on either
  repository.

## What happened

1. **A new tester onboards** (15:30:57). The laptop's client had round 2's machine and title settings, no sign-in
   and no walkthrough.
   - The walkthrough ran offscreen, page by page (`screens/walkthrough-*.png`). The "When it may run" page found
     that this laptop can't tell when it's idle (Hyprland, no idle daemon, IdleHint never set), so it greyed out
     idle and set hours (01:00–07:00). The fullscreen pause works through hyprctl.
   - The sign-in page showed a device code. standin-tester entered it, and the client signed in.
   - The register page opened issue #1, `Machine: standin-tester/laptop`.
   - After Finish, the client said "waiting for a maintainer to approve this machine" and took no jobs
     (`screens/tester-1-queue-not-ready.png`).
2. **A maintainer approves the machine with one action** (15:31:02–15:31:14).
   - CPritch signed in on a client of their own. The Overview tab listed the pending registration, with Approve
     enabled for a maintainer (`screens/maintainer-1-pending.png`).
   - Approve added the label `approved` to issue #1, as CPritch. The first time, `drive.py` crashed reading the
     table row after the click; the label was already on. The step ran again, and Approve added the label a second
     time, which changed nothing.
   - The next workflow run moved the machine into `registry.json`, replied "Approved by @CPritch" and closed the
     issue. The laptop's client was then ready.
3. **A label queues the PR** (15:31:18). CPritch added `title-test` to #8104.
   - The next workflow run pinned 69ac2e155. Its PR workflow run was at 14:31, before the label.
   - It opened job issue #4 and posted the App's comment on #8104 (`comments/1-queued.md`).
4. **The laptop runs it** (15:31:24–15:44:36). This was a real run:
   `title-runs client --config laptop.toml run-once --ignore-schedule`. The schedule said 01–07, so
   `--ignore-schedule` was needed; the readiness check still applies.
   - The client claimed the job with a comment on #4, as standin-tester.
   - It merged 69ac2e155 onto main d97361bd0 (f0a2a25b4, the same merge as round 2's) and built both sides in the
     build sandbox: 2 s and 29 s, incremental.
   - It ran the A/B in bubblewrap with warm caches: four counted runs, no pipeline builds in the windows.
   - It posted the result as a comment on #4. `screens/tester-3-running-*.png` were grabbed during the run.

   | run | p50 | GPU per present |
   |---|---|---|
   | A1 main | 77.7 ms | 62.3 ms |
   | B1 PR | 77.7 ms | 62.9 ms |
   | A2 main | 77.8 ms | 62.8 ms |
   | B2 PR | 78.0 ms | 62.6 ms |

5. **The result shows on the PR and in the overview** (15:44:44). The workflow run accepted the result: registered
   machine, earlier live claim, same job and head. It wrote `results/8104-69ac2e155ad0/laptop.json` and edited the
   App's comment (`comments/2-laptop-result.md`):
   "PPSA04263: No difference on 1 of 1 RTX 5060 Laptop GPU · NVIDIA 615 · Linux machine, median +0.13 ms (+0.2 %)".
   The +0.13 ms is inside the spread (0.30 ms) and under 1 % of main (0.78 ms), so the class is not borderline.
6. **A second machine of the class changes the combined verdict** (15:46:10). The laptop's real result was clearly
   "no difference", so real laptop numbers could only change "1 of 1" to "2 of 2". To exercise the rule, the second
   machine's numbers are **synthetic**:
   - they are today's laptop run with the PR's p50 lowered by 1.5 ms and no summary lines;
   - its machine is named `synthetic`, and its scene text says so;
   - the client itself was real: its own sign-in (standin-tester-3), registration #5, approval, claim and result
     comments.

   The combined line became "No difference on 1 of 2 … machines, median -0.62 ms (-0.8 %); borderline, one more
   machine of this class wanted" (`comments/3-synthetic-second.md`, `screens/maintainer-5-synthetic-second-fixed.png`).
7. **The scheduler asks for another machine of the class** (15:47:09). laptop-2 (standin-tester-2, registration #6)
   scored 1.01 for #8104: "RTX 5060 Laptop GPU · NVIDIA 615 · Linux: borderline on 2 machine(s), another wanted ×1".
   The synthetic machine had scored 0.20 before it reported.
   - laptop-2's numbers are the laptop's real round-2 run of the same commit: main 78.0/78.0 ms, PR 77.6/77.7 ms,
     −0.34 ms. Round 2's rule called that "faster". The 1 % rule calls it "no difference (borderline)" on that
     machine: it passes the spread but not 1 %.
   - The class settled at "No difference on 2 of 3 … machines, median -0.34 ms (-0.4 %)", with nothing more wanted
     (`comments/4-third.md`, `screens/maintainer-6-third-fixed.png`).
8. **A push expires the label** (15:47:17). Celegans12 pushed 8118a04e4, a doc-only commit on top. Its patch-ids
   differ, and the pusher is the author.
   - The workflow run expired the approval, and the App removed `title-test` (the #8104 labels are now `[]`).
   - The App's comment now leads with "**Approval of `69ac2e155` expired**: `8118a04e4` was pushed after it by
     @Celegans12 (2026-10-21 15:47 UTC) and is not checked. The App removed `title-test`; add it again to queue
     `8118a04e4`." (`comments/5-expired.md`).
   - Job issue #4 got "Approval expired …" and was closed.
   - The Overview lists the expiry under "Approvals that need a maintainer" (`screens/maintainer-7-expired.png`).
9. **Queued again** (15:49:04). CPritch added `title-test` again. 8118a04e4 had been pushed at 15:47, before the
   label, so the workflow queued it as job #7 (`comments/6-requeued.md`, `screens/maintainer-8-requeued.png`).

## Fixed during the run

- **Claims and coverage grouped by vendor and OS (2518d50).** They used the vendor and OS that `hw=` matches, not
  the GPU, driver branch and OS that verdicts are combined in. So a different NVIDIA GPU on Linux would have blocked
  the laptop's claims. The synthetic machine's 0.20 score was computed before this fix.
- **Reported machines shown as running (1722739).** The Overview listed machines that had reported as "running"
  until their claim expired. It also judged expiry by the reader's clock rather than the workflow run's.
  `screens/maintainer-4/5/6-*.png` show the bug; the `-fixed` versions are the same states (results repository
  commits 542c92f, 9f84c14 and dd0fcc7) rendered with the fix.
- **Own-sign-in writes missing from the outbox (5ca01df).** The stand-in did not record writes made with a tester's
  or maintainer's own sign-in. That covers the registration issues, the claim and result comments, and the
  Approve labels. They are all in the fake's data: `github.md` lists every issue, label event and comment there.

## Files

- `drive.py`, `steps.log`: the steps and what each one did.
- `comments/`: the App's comment on #8104 after each step.
- `screens/`: the client, as each step left it.
- `outbox/`: the writes that were recorded. The App's are `title-runs-devbot-*` and the workflow's
  `github-actionsbot-*`. See the last item above for what is missing.
- `github.md`: every issue, label event and comment in the fake GitHub.
- `relay.log`: what each workflow run did.
- `state/`: the results repository's main as the run left it.
