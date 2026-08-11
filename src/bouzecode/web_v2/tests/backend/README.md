# web_v2/tests/backend/

## Purpose

Tests for the server-side computations the web UI renders but that are not routes: the
per-turn context diagnostic, the label an agent gets in the fleet, and the shape of
generated titles.

Approach: the production functions are called directly on synthetic session records and
`Agent` objects. No Flask client, no browser, no LLM.

## Usage

- `test_context_diag.py` — `services.sessions.context_diag.build_turn_context_diag`:
  cache status and origin turn per block, plus the HTML produced by
  `context_diag_render.render_context_diag_html` and the per-call data from
  `runtime.context_viewer.builder.extract_per_call_data`.
- `test_context_diag_system_blocks.py` — the diagnostic segments on the record's
  `system_blocks` and their `cache_control`, not on message position: the cached stable
  prefix, tool docs, methodology and delta on one side; the volatile session-context
  block and the conversation messages always fresh on the other.
- `test_fleet_short_label.py` — `services.work.fleet`: the name shown for an agent is its
  subject, or failing that its role.
- `test_no_baked_time_in_titles.py` — guard: no server-generated title or label contains
  a baked `HH:MM`. The time is derived front-side from the ISO UTC `started_at`, so there
  is a single source of truth. Also covers `services.message_view` and
  `services.work.subagent_events`.
