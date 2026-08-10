"""Expose the live assistant-text deltas of an LLM turn to the web UI.

The agent runner consumes a token stream from the LLM (``TextChunk`` events in
``loop_turn.stream_llm_turn``). Those deltas were never persisted, so the web_v2
conversation tab could only show whole messages once written. This module writes
the *partial* assistant text to ``<session>.partial.json`` on every chunk (with
light throttling) so the UI can poll it and render the text as it is produced.

Contract of the ``.partial.json`` file (read by web_v2 GET /api/sessions/<key>/partial):
    {"turn": <int>, "seq": <int>, "phase": <str>, "text": <str>, "thinking": <str>}

``phase`` is ``"thinking"`` while the model reasons (native thinking tokens, before
any real assistant text) and ``"text"`` once the assistant message body starts
streaming. ``thinking`` carries the live thinking tokens; ``text`` the assistant
body (which includes any ``<tool_use>`` XML as it is produced).

``seq`` monotonically increases across writes of the same process so the UI can
tell whether the payload changed without diffing the (potentially large) text.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path

# Throttle: never write more often than this, unless enough new chars accumulated.
_MIN_INTERVAL_S = 0.12
_MIN_CHARS = 24

# Process-local write state (the runner is single agent-loop per process).
_last_write_at: float = 0.0
_last_len: int = 0
_seq: int = 0


def _partial_path(config: dict) -> Path | None:
    # Web agents (subprocess launched by web/runner.create_agent via --session-file)
    # only get ``_session_file`` set in config (cli.py); ``_session_path`` stays unset
    # until the first save_progressive lazily creates a daily-dir path. Falling back to
    # ``_session_file`` makes write_partial emit ``<agent>.session.partial.json``, which
    # is EXACTLY the file the /partial endpoint reads (ref.path.with_suffix('.partial.json')).
    session_path = config.get("_session_file") or config.get("_session_path")
    if not session_path:
        return None
    return Path(session_path).with_suffix(".partial.json")


def write_partial(
    config: dict,
    turn: int,
    text: str,
    *,
    thinking: str = "",
    phase: str = "text",
    force: bool = False,
) -> None:
    """Write the current partial assistant text/thinking, throttled.

    No-op when the session is not persisted (CLI without ``_session_path``).
    Throttled to at most one write per ``_MIN_INTERVAL_S`` unless at least
    ``_MIN_CHARS`` new characters accumulated (or ``force=True``). ``phase`` is
    ``"thinking"`` while the model reasons, ``"text"`` once the body streams.
    """
    path = _partial_path(config)
    if path is None:
        return

    global _last_write_at, _last_len, _seq
    now = time.monotonic()
    total_len = len(text) + len(thinking)
    grew = total_len - _last_len
    if not force and now - _last_write_at < _MIN_INTERVAL_S and grew < _MIN_CHARS:
        return

    _seq += 1
    _last_write_at = now
    _last_len = total_len
    payload = {"turn": turn, "seq": _seq, "phase": phase, "text": text, "thinking": thinking}
    _atomic_write_json(path, payload)


def clear_partial(config: dict) -> None:
    """Remove the ``.partial.json`` file and reset throttle state.

    Silent if the file is absent. Called at the start of a turn (reset) and once
    the complete message is ready to be persisted, so a stale partial never
    lingers to be double-rendered by the UI.
    """
    global _last_write_at, _last_len
    _last_write_at = 0.0
    _last_len = 0
    path = _partial_path(config)
    if path is None:
        return
    try:
        path.unlink()
    except OSError:
        pass


def _atomic_write_json(path: Path, payload: dict) -> None:
    """Write JSON via a temp file + rename (interrupt-safe, no torn reads)."""
    tmp = path.with_name(f"{path.name}.{uuid.uuid4().hex[:8]}.tmp")
    try:
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        try:
            tmp.unlink()
        except OSError:
            pass
