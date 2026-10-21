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

GitHub runs scheduled workflows of public repositories for free, but may delay or drop runs, and disables the schedule
after 60 days without activity in the repository: the Overview shows when the workflow last ran, and a disabled
schedule is turned back on from the Actions tab.
