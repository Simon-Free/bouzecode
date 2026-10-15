# [desc] Prompt templates for builtin Databricks and Azure deploy skills with deployment and monitoring rules [/desc]
"""Prompt bodies for the builtin deploy skills.

Split out of ``builtin.py`` so that file stays under the size limit. Registered
by ``builtin._register_builtins`` alongside the other builtin skills.

These are generic templates: adapt them to your own platform by overriding the
skill with a project skill of the same name."""
from __future__ import annotations

# ── databricks-deploy (equipment of the databricks-deployer profile) ────────

DATABRICKS_DEPLOY_PROMPT = """\
Rules for deploying / running / monitoring ingestion jobs on a **demo Databricks
workspace** (hive metastore, no Unity Catalog). Complements `demo-coding`
(uv environment, tests, refactoring).

## Environment
- Tables live in the `default` schema (e.g. `default.raw_*`) of the hive metastore.
- Delta data is stored under `dbfs:/raw/...`; use dbfs paths (no UC volumes).
- Secrets come from the Databricks secret scope `demo`; never hard-code tokens.

## Publish BEFORE deploying (never `pip install -e` on a cluster)
- Jobs pin a published package version. Publish first to your package index,
  then point the cluster libraries to `<package>==<version>`.
- TLS must stay verified (use `SSL_CERT_FILE` / `REQUESTS_CA_BUNDLE` with your
  CA bundle), NEVER `PYTHONHTTPSVERIFY=0`.

## Deploy with the `dbk` CLI
- `dbk --command "<ingest CLI command>" --schedule "<quartz cron>"` CREATES a
  scheduled job. It does NOT run it: trigger a run explicitly.
- Unset `CLUSTER_ID` before `dbk` unless you really want to reuse a cluster.

## Clusters
- Describe clusters with an explicit spec (spark version, node type, workers).
- More RAM rarely fixes an OOM: look for skew, wide shuffles, or collect()
  first; prefer streaming / batched processing.

## Monitoring
- Follow runs with the Databricks SDK (`WorkspaceClient().jobs.get_run`),
  not by guessing from CLI timeouts: a CLI `--wait` timeout is not a failure.
- Paginate `list_runs`: results are capped per page.
- Check the produced tables (row counts, max ingestion date) before declaring
  success.

## Delivery
- Report: job id, run id, final state, rows written, and the published version.
"""


# ── azure-deploy (equipment of the azure-deployer profile) ──────────────────

AZURE_DEPLOY_PROMPT = """\
Rules for deploying the **demo Azure web app**. Complements `demo-coding`.

## Deploy with `deploy.py`
- Always deploy through the project's `deploy.py`, never by hand in the portal.
- Publish the internal packages first (e.g. to Artifactory or any package
  index you use): the app installs pinned versions at build time.
- Build in a throw-away `deploy_build/` directory; never commit it.

## Run-from-package
- The app runs from a package: `wwwroot` is READ-ONLY at runtime. Write
  temporary files to `/tmp` (or the configured data dir), never to `wwwroot`.

## Runtime settings
- TLS: ship the CA bundle with the app and set `SSL_CERT_FILE` /
  `REQUESTS_CA_BUNDLE`; set `PGCLIENTENCODING` explicitly for PostgreSQL.
- Use the bundled `az` CLI from the build environment.
- Charts rendered server-side need a headless browser: set `BROWSER_PATH` to
  the bundled Chrome/Chromium.

## Verification
- After deployment, hit the health endpoint and check the displayed version
  matches the one you just tagged.
"""
