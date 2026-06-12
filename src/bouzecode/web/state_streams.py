# [desc] SSE generators that push agent state changes instead of client-side polling. [/desc]
"""Server-Sent Events streams for agent state and stdout."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Iterator

from ..web import runner
from ..web import pending as _pending
from ..web.stdout_filter import SPINNER_RE as _SPINNER_RE, ANSI_RE as _ANSI_RE, ansi_line_to_html


_STREAM_TICK_SECONDS = 0.5
_LIST_TICK_SECONDS = 2.0


def build_agent_state(agent: runner.Agent) -> dict:
    runner.refresh_agent_status(agent)
    ipc_state = runner.get_ipc_state(agent)
    session_mtime = None
    if agent.session_path:
        session_path = Path(agent.session_path)
        if session_path.exists():
            session_mtime = session_path.stat().st_mtime
    return {
        "running": runner.is_running(agent),
        "ipc_status": ipc_state.get("status", "unknown"),
        "returncode": agent.returncode,
        "question": ipc_state.get("question"),
        "options": ipc_state.get("options"),
        "allow_freetext": ipc_state.get("allow_freetext", True),
        "session_mtime": session_mtime,
    }


def _state_diff_key(state: dict) -> tuple:
    return (
        state["running"],
        state["ipc_status"],
        state["returncode"],
        state["question"],
        state["session_mtime"],
    )


def generate_agent_stream(agent: runner.Agent, initial_offset: int = 0) -> Iterator[str]:
    """Yield SSE frames combining stdout lines (`data:`) and state changes (`event: state`)."""
    offset = initial_offset
    last_state_key = None

    state = build_agent_state(agent)
    yield f"event: state\ndata: {json.dumps(state)}\n\n"
    last_state_key = _state_diff_key(state)

    if not state["running"]:
        yield "event: done\ndata: end\n\n"
        return

    while True:
        chunk, offset = runner.read_stdout(agent, offset)
        if chunk:
            for raw_line in chunk.splitlines(keepends=False):
                stripped = _ANSI_RE.sub("", raw_line).rstrip()
                if not stripped or _SPINNER_RE.match(stripped):
                    continue
                html_line = ansi_line_to_html(raw_line)
                yield f"data: {html_line}\n\n"

        state = build_agent_state(agent)
        key = _state_diff_key(state)
        if key != last_state_key:
            yield f"event: state\ndata: {json.dumps(state)}\n\n"
            last_state_key = key

        if not state["running"]:
            yield "event: done\ndata: end\n\n"
            return

        time.sleep(_STREAM_TICK_SECONDS)


def _agent_category(agent: runner.Agent) -> str:
    ipc_status = runner.get_ipc_state(agent).get("status")
    if ipc_status in ("awaiting_input", "awaiting_plan_validation"):
        return "awaiting"
    if not runner.is_running(agent) or ipc_status == "finished":
        return "finished"
    return "running"


def generate_agents_list_stream() -> Iterator[str]:
    """Yield SSE frames (`event: agents`) whenever the set of live agents changes category."""
    last_snapshot: list[dict] | None = None
    while True:
        agents = runner.list_agents()
        snapshot = []
        for agent in agents:
            runner.refresh_agent_status(agent)
            snapshot.append({"id": agent.agent_id, "cat": _agent_category(agent)})

        if snapshot != last_snapshot:
            yield f"event: agents\ndata: {json.dumps(snapshot)}\n\n"
            last_snapshot = snapshot

        time.sleep(_LIST_TICK_SECONDS)
