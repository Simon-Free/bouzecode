# web_v2/tests/

## Purpose

Tests for the Flask web UI shipped inside the package: its routes, its SQLite ticket
store, the agent park, and the orchestration services behind them. Most tests drive the
real application through the Flask test client, over real (temporary) git repositories
and a real store. No LLM is ever called.

Every test runs under the autouse isolation in `conftest.py`, which redirects the ticket
store, the agent park, the worktree root and the project registry into `tmp_path`, so no
test can read or write the user's real state.

This tree sits outside `testpaths`, so it must be passed explicitly:
`pytest src/bouzecode/web_v2/tests -n auto`.

## Usage

Harness and shared decor:

- `conftest.py` — autouse `_isolate_production_state` and `_forget_session_caches`;
  disables the wake poller before the app can be built.
- `production_isolation.py` — `isoler_le_parc_d_agents`, `autoriser_la_destruction`,
  `verifier_le_parc_est_isole`: the agent-park redirection, shared with `tests/web_v2/`.
- `delivery_repo.py` — delivery fixtures: `develop_repo`, `agents_dir`, `project`,
  `client`, `delivered_ticket`, `finished_agent`, `block_git_index`, `git_out`.
- `scope_guard_prompts.py` — prompt corpus (`DIRECTE_*`, `INDIRECTE_*`, `MESURE_*`) fed
  to the scope-guard tests.
- `dead_spy_audit.py` — opt-in pytest plugin listing `monkeypatch.setattr` spies never
  invoked.

Test families, by filename prefix:

- `test_no_real_agent_is_ever_touched`, `test_production_store_is_isolated`,
  `test_purge_never_touches_a_live_agent`, `test_terminate_identity_guard`,
  `test_relaunch_isolation_guard`, `test_port_guard` — guards that neither the suite nor
  the server ever touches a live process or real data.
- `test_ticket*`, `test_workflow*`, `test_reaper`, `test_legacy_json_migration`,
  `test_migrate_inflight_tickets`, `test_refresh_verdicts_concurrency`,
  `test_completed_endpoint` — SQLite ticket store, reversible archiving, connection
  reuse, state machine, verdict parsing, sandbox GC.
- `test_dispatch_*`, `test_scope_guard`, `test_coder_flow` — routing a prompt to a
  project, project inheritance, work-branch requests, duplicate-scope and read-only
  refusals, and the coding ticket journey up to the merge.
- `test_crash_markers`, `test_api_crash_no_validate`, `test_stale_crash_revoked`,
  `test_closure_guard*`, `test_status_agrees_with_liveness`, `test_reconcile_*`,
  `test_childless_manager_status`, `test_fire_completion_stamps_session`,
  `test_returncode_ipc_fallback`, `test_wake_*`, `test_auto_resume_*`,
  `test_restore_state_roundtrip`, `test_killed_agent_stops_waiting`,
  `test_unreachable_agent_is_named` — crash detection, graceful closure and its IPC
  fallback, the wake reconciler and its idle cost.
- `test_interrupt_*`, `test_agent_interrupt_api`, `test_*warm*`,
  `test_reap_orphan_processes`, `test_interrupted_deleted` — soft interrupt via
  `cancel.flag`, warm-pool reachability, orphan process reaping.
- `test_agents_tree_api`, `test_fleet_*`, `test_*_is_visible`, `test_tree_phase_is_live`,
  `test_launching_conversation_names_its_phase`, `test_new_agent_visible_without_ttl_wait`,
  `test_delivery_views_agree`, `test_subagent_events` — what the agent tree shows, and at
  what moment.
- `test_conversations_*`, `test_continue_*`, `test_message_view`,
  `test_final_answer_display`, `test_turn_context_button`, `test_home_redirect` — the
  conversations page: classification, archiving, safe purge, message rendering.
- `test_api_session_recap`, `test_sessions_*`, `test_zoom_endpoints`,
  `test_recap_merge_body` — session listing cost and caching, grep, profile, purge,
  recap, and zooming into a turn or a tool call.
- `test_worktree*`, `test_repos_*`, `test_parc_reclaim`, `test_relaunch_preserves_work`,
  `test_relaunch_route_keeps_commits`, `test_agent_knows_its_branch`,
  `test_delivery_harvest`, `test_merge_dirty_base`, `test_integration_auto` — real git
  worktrees, venv borrowing, disk accounting, commit preservation across relaunch, merge
  and harvest.
- `test_agent_builder_page`, `test_agent_catalog_api`, `test_agent_share_api`,
  `test_profiles_api`, `test_projects_description` — agent-builder pages, profile
  round-trip, plugin installation, project descriptions.
- `test_schema_coverage`, `test_route_json_body_bound`, `test_static_cache_headers`,
  `test_store_cache_race` — route contracts, cache headers, concurrent cache writes.

## Subfolders

| Folder | Description |
|--------|-------------|
| `backend/` | Server-side computations rendered into pages: context diagnostic, fleet labels, title shape. |
| `js/` | The real `static/js/` scripts run in a simulated DOM (happy-dom) under Vitest, without a browser. |
| `playwright/` | Behaviours invisible to the Flask test client: computed CSS, pixel geometry, real JavaScript, real clicks. |
