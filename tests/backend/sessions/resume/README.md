# sessions/resume/

## Purpose

Covers crash recovery of web agents: `bouzecode.web_v2.runtime.runner` and
`web_v2.runtime.ipc` decide, from the files an agent left behind, whether to respawn it when
the server restarts. Unit level on purpose — the behaviour spans two processes, so the tests
reproduce the on-disk contract (agent JSON, IPC `state.json`, session JSON) under `tmp_path`
rather than starting a subprocess. `test_session_analysis.py` sits here as the reader side of
the same session files.

## Usage

- `test_resume_interrupted.py` — `_session_has_pending_tool_calls` and
  `resume_interrupted_agents`: an agent with unanswered tool calls is respawned, a finished or
  cancelled one is not, and `run_agent_event_loop` leaves `STATUS_RUNNING` on `KeyboardInterrupt`
  so the restart reads it as a crash.
- `test_resume_interrupted_no_pending.py` — an interrupted agent with no pending tool call is
  resumed too.
- `test_resume_plan_validation.py` — an agent parked on plan validation keeps that category
  (`runtime.state_streams._agent_category`) across a restart instead of being marked crashed,
  while genuinely dead agents still are.
- `test_session_analysis.py` — `agent.session_analysis`: `analyze_turn_segments` splitting a
  turn payload into cache-read and cache-write segments, `load_payload_dump`,
  `analyze_session_turn`, and an out-of-range turn index.
