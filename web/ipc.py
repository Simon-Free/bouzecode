# [desc] File-based IPC contract between BouzéGUI and the bouzecode agent subprocess (state, followup, answer, cancel). [/desc]
"""File-based IPC between BouzéGUI and the bouzecode agent subprocess.

Layout in <ipc_dir>/:
  state.json     — agent status + optional awaiting-input payload
  followup.txt   — UI writes next user turn; agent reads & deletes
  answer.txt     — UI writes answer to AskUserQuestion; tool reads & deletes
  cancel.flag    — UI touches to request turn cancellation; agent reads & deletes

Statuses:
  running          — agent actively processing a turn
  awaiting_input   — AskUserQuestion is blocked waiting for answer.txt
  idle             — final answer delivered, waiting for followup.txt
  finished         — process is exiting
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

STATUS_RUNNING = "running"
STATUS_AWAITING_INPUT = "awaiting_input"
STATUS_IDLE = "idle"
STATUS_FINISHED = "finished"

ENV_IPC_DIR = "BOUZECODE_WEB_IPC_DIR"


@dataclass
class IPCPaths:
    root: Path

    @property
    def state(self) -> Path:
        return self.root / "state.json"

    @property
    def followup(self) -> Path:
        return self.root / "followup.txt"

    @property
    def answer(self) -> Path:
        return self.root / "answer.txt"

    @property
    def cancel(self) -> Path:
        return self.root / "cancel.flag"


def from_dir(path: str | os.PathLike) -> IPCPaths:
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return IPCPaths(p)


def from_env() -> IPCPaths | None:
    raw = os.environ.get(ENV_IPC_DIR)
    return from_dir(raw) if raw else None


def write_state(paths: IPCPaths, status: str, **extra) -> None:
    payload = {"status": status, "updated_at": time.time(), **extra}
    tmp = paths.state.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    tmp.replace(paths.state)


def read_state(paths: IPCPaths) -> dict:
    if not paths.state.exists():
        return {"status": "unknown"}
    try:
        return json.loads(paths.state.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"status": "unknown"}


def pop_text(path: Path) -> str | None:
    """Read and delete a file atomically. Returns content, or None if missing."""
    if not path.exists():
        return None
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        path.unlink()
    except OSError:
        pass
    return content


def is_cancelled(paths: IPCPaths) -> bool:
    return paths.cancel.exists()


def consume_cancel(paths: IPCPaths) -> bool:
    if not paths.cancel.exists():
        return False
    try:
        paths.cancel.unlink()
    except FileNotFoundError:
        pass
    return True


def run_agent_event_loop(initial_prompt, run_query, paths: IPCPaths) -> None:
    """Execute a single turn then exit.

    BouzéGUI drives multi-turn conversations by respawning a new subprocess per
    turn (see `web/runner.py::continue_agent`). This loop runs one turn and
    writes `finished` on exit. Paused turns (AskUserQuestion) write
    `awaiting_input` from `_persist_pause_and_exit` before raising SystemExit —
    the finished-write below is skipped in that path."""
    write_state(paths, STATUS_RUNNING, turn=1)
    try:
        run_query(initial_prompt)
    except KeyboardInterrupt:
        pass
    write_state(paths, STATUS_FINISHED, turn=1)
