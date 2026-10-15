"""Official stream interception point for bouzecode LLM calls.

Provides set_stream_interceptor / get_streamer so external apps (e.g. Focus)
can wrap the LLM stream without monkeypatching internals.
"""
from __future__ import annotations

from typing import Callable, Generator

_interceptor: Callable | None = None


def set_stream_interceptor(fn: Callable | None) -> None:
    """Register a global stream interceptor.

    *fn* receives the current stream callable and must return a callable
    with the same signature::

        (model, system, messages, tool_schemas, config) -> Generator

    Only one interceptor is active at a time — the last call wins.
    Pass ``None`` to restore the default (no interception).
    """
    global _interceptor
    _interceptor = fn


def get_streamer() -> Callable[..., Generator]:
    """Return the effective stream callable (intercepted or raw).

    Resolves ``loop_turn.stream`` dynamically each time so that
    monkeypatching (as done by the e2e test harness) continues to work
    transparently.
    """
    from . import loop_turn as _lt

    raw = _lt.stream
    if _interceptor is not None:
        return _interceptor(raw)
    return raw
