# AnyPS5 title runs: results repository

The queue, the registered machines and the accepted results of AnyPS5 title runs, kept by this repository's one
workflow, `relay` (see the tool's DESIGN.md and FORMATS.md). Public: testers' clients read it, and testers report
through issues and comments with their own GitHub sign-in. Nobody but the workflow and the maintainers writes it.

Issues here:

- **Job …**: one per queued PR head, opened by the workflow; testers' clients claim and report in comments.
- **Machine …**: a tester's registration. Add the label `approved` to approve the machine, `declined` to turn it down.
- **Overview**: the queue, coverage, machines and pending registrations, kept up to date by the workflow. Pin it.
- **Runs on testers' own trust**: results of heads no maintainer approved.

Setting it up (one App, this repository, one secret):

1. Create the GitHub App: no webhook (uncheck "Active"); enable Device Flow; repository permissions Issues read and
   write, Pull requests read and write, Metadata read. Generate a private key.
2. Install it on AnyPS5 and on this repository.
3. In this repository's settings, add the secret `APP_PRIVATE_KEY` (the private key's contents).
4. Fill `config.json`: the App's ID, client ID and bot name (`<app-slug>[bot]`), the maintainers, and the tool's
   repository and the commit to run.
5. Run the workflow once from the Actions tab (Run workflow), then pin the Overview issue it opens.

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
