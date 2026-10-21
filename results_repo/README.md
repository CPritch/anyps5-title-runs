# AnyPS5 title runs: results repository

The queue, the registered machines and the accepted results of AnyPS5 title runs, kept by this repository's one
workflow, `relay` (see the tool's DESIGN.md and FORMATS.md). Public: testers' clients read it, and testers report
through issues and comments with their own GitHub sign-in. Nobody but the workflow and the maintainers writes it.

Issues here:

- **Job …**: one per queued PR head, opened by the workflow; testers' clients claim and report in comments.
- **Machine …**: a tester's registration. Add the label `approved` to approve the machine, `declined` to turn it down.
- **Overview**: the queue, coverage, machines and pending registrations, kept up to date by the workflow. Pin it.
- **Runs on testers' own trust**: results of heads no maintainer approved.

Setting it up (one App, this repository, one secret; the tool's docs/first-real-test.md has the same steps with
checks):

1. Create the GitHub App from its manifest: `title-runs app create --results-repo <this repository's checkout>
   --out <a folder outside every repository>`, then **Create GitHub App** on the page GitHub shows. It has no webhook
   and these repository permissions: Actions read, Issues read and write, Pull requests read and write, Metadata
   read. The private key stays in the folder given to `--out`; the App's ID, client ID and bot name are written into
   `config.json` and committed.
2. In the App's settings, under "Identifying and authorizing users", tick **Enable Device Flow** and save. Testers
   sign in with it.
3. Install the App: **Only select repositories**, AnyPS5 and this repository.
4. Push this repository (public), and add the secret `APP_PRIVATE_KEY` with the private key's contents:
   `gh secret set APP_PRIVATE_KEY -R OWNER/NAME < KEY.pem`.
5. Run the workflow once from the Actions tab (**relay**, **Run workflow**), then pin the Overview issue it opens.

Settings in `config.json` besides the names: `maintainers` (whose labels and commands count), `label`, and
`verdicts`: `threshold_pct` (a difference must exceed this share of main's p50, default 1) and `class_max` (how many
machines a borderline class asks for, default 3).

## When the workflow stops running

GitHub runs scheduled workflows of public repositories for free, but may delay or drop runs, and **disables the
schedule after 60 days without activity in the repository**. The Overview issue says when the workflow last ran,
and testers' clients warn when that is more than an hour ago.

To turn a disabled schedule back on (a maintainer with write access):

1. Open the repository's **Actions** tab and pick **relay** in the list of workflows on the left.
2. GitHub shows "This scheduled workflow is disabled because there hasn't been activity in this repository for at
   least 60 days". Press **Enable workflow**.
3. Press **Run workflow** (the button on the right of the run list) once, so it catches up now instead of at the
   next scheduled time. Nothing is lost while it was off: the workflow keeps cursors and reads everything since.

Or from a terminal: `gh workflow enable relay -R OWNER/NAME && gh workflow run relay -R OWNER/NAME`.

Check it worked: a new run appears in the Actions tab within a few minutes, and the Overview issue's "Updated by the
relay workflow at …" line shows the new time.
