# web_v2/runtime/

## Purpose
The server side of an agent process: spawn the CLI as a subprocess, persist and
track it, exchange turns with it through files on disk, and stream what it
prints to the browser.

## Usage
- `runner.py` — `Agent`, `create_agent()`, `load_agent()`, `list_agents()`, `refresh_agent_status()`, `is_running()`, `is_mid_turn()`, `read_stdout()`, `get_ipc_state()`, `resume_agent()`, `continue_agent()`, `resume_pending_agent()`, `resume_deferred_agent()`, `resume_auto_agent()`, `resume_interrupted_agents()`, `reconcile_dead_agents()`, `kill_agent()`, `graceful_cancel_agent()`, `terminate_agent_process()`, `signal_termination()`, `reap_session_processes()` (which WAITS for its victims, bounded,
and counts only the processes confirmed dead — `terminate()` alone merely asks),
`destruction_permitted()`, `check_provider_env()`, `MissingProviderEnvError`, `AGENTS_DIR`, `RESUME_PROMPT` — the whole subprocess lifecycle: spawn environment and profile arguments, one `<id>.json` per agent under `AGENTS_DIR` with a short-lived list cache, status derived from the process, the IPC state and the session's close reason, follow-up pushed to a warm process instead of respawning, and the deferred-check drain.
- `ipc.py` — `IPCPaths`, `from_dir()`, `from_env()`, `write_state()`, `read_state()`, `pop_text()`, `is_cancelled()`, `consume_cancel()`, `run_agent_event_loop()`, `STATUS_RUNNING`/`STATUS_AWAITING_INPUT`/`STATUS_IDLE`/`STATUS_FINISHED`, `ENV_IPC_DIR` — the file protocol (`state.json`, `followup.txt`, `answer.txt`, `cancel.flag`), the heartbeat carried by `updated_at`, and the agent-side loop that runs a turn then stays warm polling for a follow-up until cancel or TTL.
- `pending.py` — `pending_path()`, `save()`, `load()`, `delete()`, `exists()`, `cancel()` — `<session>.pending.json` for a turn paused on a question; `cancel()` injects synthetic tool results so the conversation stays valid.
- `deferred.py` — `deferred_path()`, `save()`, `load()`, `delete()`, `exists()` — `<session>.deferred.json` holding the final answer and the commands queued for after the turn.
- `warmpool.py` — `decide_evictions()`, `ACTIVE_STATES`, `DEFAULT_TTL_SECONDS` — pure policy deciding which warm agents lose their live process: sub-agents once inactive, anything past the inactivity TTL, then least-recently-active under pressure, never an agent with an active descendant.
- `state_streams.py` — `build_agent_state()`, `generate_agent_stream()`, `generate_agents_list_stream()` — Server-Sent Events pushing stdout lines and state changes for one agent, and category changes for the whole list.
- `stdout_filter.py` — `ansi_line_to_html()`, `clean_stdout()`, `ANSI_RE`, `SPINNER_RE` — terminal output to HTML spans, simulating carriage-return overwrite and dropping spinner frames.
- `venv_env.py` — `venv_bin_dir()`, `is_usable()`, `base_venv_env()` — the variables that point an agent at the base repository's virtual environment so a worktree does not build one of its own.

## Subfolders
| Folder | Description |
|--------|-------------|
| `context_viewer/` | Per-call context reconstruction with token and cache badges |
| `html_renderer/` | Saved session to a self-contained HTML page |
| `tests/` | Unit tests for the runner, IPC, deferred store and warm pool |
