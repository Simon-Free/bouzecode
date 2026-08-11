# sessions/

## Purpose

Covers what a run leaves behind: the session payload assembled by
`bouzecode.backend.commands.session._build_session_data`, and the fields the agent loop sets on
`AgentState` that end up in it. Two files run real conversations through
`tests.e2e_harness.bouzecode`; the others drive `agent.loop.run` over a fake stream with tools
registered in the real `core.tool_registry`.

## Usage

- `test_session_save_e2e.py` — a real conversation, then `_build_session_data`: thinking
  preserved, tool_use XML stripped, a thinking-only message kept, a tool-only turn collapsed to
  a dot, `context_state` notes recorded, and `commands.core.basic.cmd_clear` wiping them.
- `test_session_live_saves.py` — during `agent.loop.run` and `resume_paused`, a consumer
  observing each `ToolEnd` / `TurnDone` can write a session file reflecting the current
  `state.messages`.
- `test_close_reason.py` — the `close_reason` telemetry set by `loop.run`: text with no tool
  calls, `FinalAnswer` ending the session, and a text close after real work.
- `test_final_answer_persistence.py` — `final_answer` is serialized by `_build_session_data` and
  read back by `web_v2.services.sessions.store.session_meta_full`, empty when never set.
- `test_bouzecode_version_t103.py` — `agent.loop._get_bouzecode_version` returns the version
  declared in `pyproject.toml`, never `unknown`.

## Subfolders

| Folder | Description |
|--------|-------------|
| `persistence/` | Writing the session to disk: atomic write, backup rotation, checkpoints, restore. |
| `resume/` | Deciding from the files left on disk whether a crashed agent must be respawned. |
