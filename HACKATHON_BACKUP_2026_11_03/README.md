# HACKATHON_BACKUP_2026_11_03

Migration bundle for the FEMA Evidence & Oversight hackathon submission
(Phebe Arouni & Tom Jacobson). It moves the latest working version of the
submission from the old (going-away) Databricks workspace to a new one.

## What the bundle recreates

| Old workspace | Bundle file | New workspace |
| --- | --- | --- |
| App `2026h` (release `hackathon_releases/20261102`) | `resources/fema_oversight.app.yml`, `src/app/` | App `2026h` (variable `app_name`) |
| Judge package (walkthrough notebook, README_FOR_JUDGES.md, frozen Oct 29 zip) | `src/judge/` | Synced to the bundle folder |
| Job 237307315987127 + load notebook | `resources/hackathon_data.jobs.yml`, `src/notebooks/` | Job *Load FEMA Funded Projects* |
| Dashboard *FEMA Public Assistance Funding Overview* | `resources/fema_pa_overview.dashboard.yml`, `src/dashboards/` | Same dashboard |
| MLflow experiment *FEMA Hackathon Evaluation* | `resources/hackathon_eval.experiment.yml` | Same name in your user folder |
| Volume `users.phebe_arouni.hackathon_submissions` | `resources/hackathon_submissions.volume.yml` | `<catalog>.<schema>.hackathon_submissions` |
| Genie space, golden eval dataset, MLflow run history, packet files | `migration_data/` | Restored by job *Restore FEMA hackathon data* |
| Table `funded_projects_details` rows | (not copied) | Reloaded from the public OpenFEMA API |

Not included (by choice): release 20261029, the `fema-oversight-mcp` folder,
superseded zips (`superseded_rev1/2`, `cleaned_workspace_zips`).
The rest of the `2026-HACKATHON` repo (MCP server source, tests, eval, docs)
moves with the Git push.

## Migration steps

**In the OLD workspace (before it goes away)**

1. Run `src/notebooks/01_snapshot_from_current_workspace` top to bottom.
   It must end with `ALL COPIES VERIFIED`.
2. Optional test: `databricks bundle validate --strict -t dev`, then
   `databricks bundle deploy -t dev` (creates side-by-side copies; the live
   app 2026h is not touched).
3. Commit and push the `2026-HACKATHON` Git folder (includes this bundle) to
   GitHub `phebeong/2026-HACKATHON`.

**In the NEW workspace**

4. Clone the repo as a Git folder (or locally) and open
   `HACKATHON_BACKUP_2026_11_03`.
5. Make sure the catalog/schema exist (defaults `workspace.default`) and the
   serving endpoint `databricks-claude-haiku-4-5` is available.
6. Deploy:
   ```
   databricks bundle deploy -t new_env --var="warehouse_id=<WAREHOUSE_ID>"
   ```
   Add `--var="catalog=..." --var="schema=..."` if not `workspace.default`.
7. Restore data (also reloads the PA table from OpenFEMA):
   ```
   databricks bundle run restore_hackathon_data -t new_env --var="warehouse_id=<WAREHOUSE_ID>"
   ```
8. Start the app:
   ```
   databricks bundle run fema_oversight_app -t new_env --var="warehouse_id=<WAREHOUSE_ID>"
   ```
9. Re-share with tom.jacobson@hq.dhs.gov (app, Genie space, warehouse,
   volume, table) and update any links in README_FOR_JUDGES.md that point to
   the old workspace URL or `/Volumes/users/phebe_arouni/...`.

## Known gaps

* MLflow run *artifacts* (reports, traces) are not copied; params, metrics
  and tags are. Download any artifact you need from the old experiment.
* The judge notebook looks for zips in old paths; it falls back to
  `src/judge/FEMA_Hackathon_Submission_2026-10-29.zip` only if you update
  its `CANDIDATE_ZIPS` list to the new volume path.
* If you change `model_endpoint`, also set `FEMA_AGENT_MODEL` in
  `src/app/app.yaml`.


## Getting started

Choose how you want to work on this project:

(a) Directly in your Databricks workspace, see
    https://docs.databricks.com/dev-tools/bundles/workspace.

(b) Locally with an IDE like Cursor or VS Code, see
    https://docs.databricks.com/dev-tools/vscode-ext.html.

(c) With command line tools, see https://docs.databricks.com/dev-tools/cli/databricks-cli.html

If you're developing with an IDE, dependencies for this project should be installed using uv:

*  Make sure you have the UV package manager installed.
   It's an alternative to tools like pip: https://docs.astral.sh/uv/getting-started/installation/.
*  Run `uv sync --dev` to install the project's dependencies.


# Using this project using the CLI

The Databricks workspace and IDE extensions provide a graphical interface for working
with this project. It's also possible to interact with it directly using the CLI:

1. Authenticate to your Databricks workspace, if you have not done so already:
    ```
    $ databricks configure
    ```

2. See "Migration steps" above for the deploy and run commands
   (`dev` = old workspace test copy, `new_env` = new workspace).
