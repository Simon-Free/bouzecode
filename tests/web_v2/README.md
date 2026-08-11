# tests/web_v2/

## Purpose

Second tree of tests for the Flask web UI, collected by default (unlike
`src/bouzecode/web_v2/tests/`, which sits outside `testpaths`). It concentrates on the
orchestration services behind the routes: status derivation, the wake reconciler,
dispatch, isolation, worktrees, session reads.

Approach: the real services and the real Flask test client over `tmp_path`, real git
repositories for the worktree tests, injected fakes rather than `mock.patch`. No LLM.

## Usage

`conftest.py` imports `_isolate_production_state` and `_forget_session_caches` from
`bouzecode.web_v2.tests.conftest`, giving this tree the same autouse redirection of the
ticket store, agent park, worktrees and project registry into `tmp_path`. Importing
rather than copying keeps the two guards from diverging.

Test families, by filename prefix:

- `test_agent_isolation`, `test_isolation_*`, `test_runner_spawn_isolation`,
  `test_runner_continue_empty_session` — isolation requested at launch (shared /
  worktree / worktree+venv), the anti-collision guard counting only write-capable agents,
  and the refusal to degrade silently when isolation is impossible.
- `test_no_real_agent_is_ever_touched` — this tree never enumerates or kills a real agent.
- `test_liveness`, `test_close_reasons_table`, `test_derive_*`, `test_demarrage_phase`,
  `test_agent_status_starting`, `test_agent_tree_launching`,
  `test_status_cache_invalidate` — the evidence-based liveness classifier, the statuses
  derived from it, and the launching/starting phases.
- `test_wake_*`, `test_reconcile_retire_crashed`, `test_finalize_noncoding_garde_crashed`,
  `test_launch_failure_wakes_parent` — waking a manager, reconciling its children, and
  the races around graceful closure.
- `test_dispatch_*`, `test_tickets_create_defer`, `test_tickets_concurrency`,
  `test_ticket_done_acquitte` — deferred launch, prompt passed through untouched, atomic
  ticket writes, acknowledging a blocked merge.
- `test_typologies`, `test_typology_default` — typologies built from real profile YAMLs
  and builtin agent definitions, default always first.
- `test_auto_resume`, `test_recovery`, `test_interrupted_report` — boot-time resume of
  crashed sub-agents and the manual recovery path.
- `test_fleet_warm`, `test_warmpool_sous_agents` — git pre-warming in the fleet tree and
  warm-pool eligibility.
- `test_search`, `test_session_*`, `test_costs`, `test_items_full_text`,
  `test_turn_detail_full_content`, `test_conversations`, `test_messaging`,
  `test_partial_stream*` — session listing and sorting, search, cost aggregation, recap
  diffs, full turn content, token-by-token streaming.
- `test_worktree_integration_merge`, `test_worktree_provision_retry` — merging an
  isolated worktree back, and retrying its provisioning.
- `test_i18n_*` — the two dictionaries agree, no page shows a missing key, pages ship in
  English with a language selector.
- `test_version_cache`, `test_version_drift` — `version_state` drift detection and the TTL
  cache behind `GET /api/version`.
- `test_api_sanity` — the API environment verdict: missing env vs unreachable base URL,
  retries, re-probing, and the 503 guards on spawns.

## Subfolders

| Folder | Description |
|--------|-------------|
| `services/` | Unit tests of pure service functions, mirroring the `services/` package layout. |
