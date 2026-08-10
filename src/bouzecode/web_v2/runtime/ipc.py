"""File-based IPC between BouzéqUI and the bouzecode agent subprocess.

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

state.json payload: ``{status, updated_at, turn, ...extra}``. ``updated_at`` (epoch, written
by every ``write_state``) is the agent's HEARTBEAT — a "running" whose ``updated_at`` is ten
minutes old says something a bare "running" cannot. ``tools`` carries the tool names of the
batch currently executing (see ``dag._announce_activity``): during tool execution it is the
ONLY live trace of what the agent is doing, the partial stream having already been cleared
and the session not yet saved. Both are surfaced by ``store.agent_status``.
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
    """Best-effort : sous Windows, replace échoue (WinError 5) si le serveur lit
    state.json au même instant — vu en prod 2026-06-10, un WritePlan a tué tout
    un run d'agent. Quelques retries puis abandon silencieux : l'état est
    purement consultatif et sera réécrit au prochain changement."""
    payload = {"status": status, "updated_at": time.time(), **extra}
    tmp = paths.state.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    for attempt in range(5):
        try:
            tmp.replace(paths.state)
            return
        except PermissionError:
            time.sleep(0.05 * (attempt + 1))
    try:
        tmp.unlink()
    except OSError:
        pass


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


def _maybe_bootstrap_readme(root: Path) -> None:
    """Run the readme_sync launch hook if the package is importable.

    `readme_sync` lives at the repo root and is NOT guaranteed on an agent's
    import path (isolated worktrees, an installed venv exposing only the
    `bouzecode` package). A missing package must never crash agent startup, so
    probe for it before importing; the hook itself is gated OFF by default."""
    import importlib.util

    if importlib.util.find_spec("readme_sync") is None:
        return
    from readme_sync.bootstrap import maybe_bootstrap_readme

    maybe_bootstrap_readme(root)


def run_agent_event_loop(initial_prompt, run_query, paths: IPCPaths,
                         keep_warm: bool = True, ttl_seconds: float = 900.0,
                         poll_interval: float = 0.5) -> None:
    """Execute a turn, then (if keep_warm) stay resident in a warm idle loop.

    Warm path: after a clean finish, instead of exiting (cold respawn on the next
    follow-up), the process writes `idle` and polls `followup.txt`. When a
    follow-up arrives it is consumed IN-PROCESS (context stays in RAM → zero
    cold-start). The loop exits (→ FINISHED) on cancel or after `ttl_seconds` of
    inactivity. Paused turns (AskUserQuestion / plan validation) return early and
    are kept warm by repl._resume_paused_warm instead. keep_warm=False restores
    the legacy single-turn behavior (write FINISHED and exit)."""
    def _run_one(prompt) -> str:
        """Run one turn. Returns 'awaiting' (paused), 'finished', or 'error' (already wrote FINISHED + must re-raise)."""
        _existing = read_state(paths)
        write_state(paths, STATUS_RUNNING, turn=_existing.get("turn", 1))
        _maybe_bootstrap_readme(Path.cwd())
        try:
            run_query(prompt)
        except KeyboardInterrupt:
            return "awaiting"  # graceful stop, don't clobber state
        except Exception:
            # Fatal error (e.g. provider connection exhausted): do NOT leave the IPC
            # stuck on 'running' — write FINISHED so web_v2 stops treating the agent
            # as alive, then re-raise so the process exits non-zero. The disk session
            # carries close_reason='api_error' (persisted by run_query), which is what
            # the runner/web_v2 use to distinguish this from a graceful finish.
            current = read_state(paths)
            write_state(paths, STATUS_FINISHED, turn=current.get("turn", 1))
            raise
        current = read_state(paths)
        if current.get("status") in ("awaiting_plan_validation", "awaiting_input"):
            return "awaiting"
        return "finished"

    outcome = _run_one(initial_prompt)
    if outcome == "awaiting":
        # Tool set an awaiting state (WritePlan validation / AskUserQuestion) — leave it.
        return
    # outcome == "finished"
    if not keep_warm:
        # Legacy single-turn: don't clobber a FINISHED already written by
        # _ipc_finish_cb (real turn + close_reason) with a bare turn=1 finish.
        current = read_state(paths)
        if current.get("status") not in ("awaiting_plan_validation", "awaiting_input", STATUS_FINISHED):
            write_state(paths, STATUS_FINISHED, turn=current.get("turn", 1))
        return

    # Warm idle loop: stay resident, poll followup.txt for the next turn.
    while True:
        current = read_state(paths)
        write_state(paths, STATUS_IDLE, turn=current.get("turn", 1))
        last_activity = time.monotonic()
        prompt = None
        while True:
            if is_cancelled(paths) or consume_cancel(paths):
                current = read_state(paths)
                write_state(paths, STATUS_FINISHED, turn=current.get("turn", 1))
                return
            prompt = pop_text(paths.followup)
            if prompt is not None:
                break
            if time.monotonic() - last_activity > ttl_seconds:
                current = read_state(paths)
                write_state(paths, STATUS_FINISHED, turn=current.get("turn", 1))
                return
            time.sleep(poll_interval)
        outcome = _run_one(prompt)
        if outcome == "awaiting":
            return
