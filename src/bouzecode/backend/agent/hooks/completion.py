# [desc] Builtin `run_completion_chain` hook: on graceful close, notify the server to advance this ticket's workflow. [/desc]
"""Builtin on_completion hook wired by coder profiles.

When a governed coder/validator agent closes gracefully, this hook tells the
server "I'm done" via the stable HookContext helpers (NEVER a direct import of
services/work/*). The server then advances the ticket's declarative workflow
state machine (spawn validator → validate → merge/rework). Ungoverned/CLI agents
(``self_id`` empty) are a no-op.

Exported as ``HOOK_DEFS`` so the pipeline catalog picks it up exactly like a
plugin would (mirror of ``TOOL_DEFS``).
"""
from __future__ import annotations

from .pipeline import HookDef


def run_completion_chain(ctx) -> None:
    """Notify the server that this agent finished; the server advances the chain."""
    if not ctx.self_id:
        return  # ungoverned / CLI agent — nothing to orchestrate
    import os

    slug = os.environ.get("BOUZECODE_TICKET_SLUG", "")
    ticket_id = os.environ.get("BOUZECODE_TICKET_ID", "")
    if not (slug and ticket_id):
        return  # not attached to a ticket — nothing to advance
    if ctx.close_reason == "api_error":
        # An API crash (provider outage after retries exhausted) is NOT a graceful
        # close: never advance the coder->validator->merge chain. The crash is
        # reconciled server-side by wake._reconcile_api_crash, which routes the
        # ticket to the visible `crashed` terminal state instead of validating.
        return
    # Generous timeout: the server runs the deterministic test-gate (full suite)
    # synchronously inside this request before returning.
    # close_reason lets the server distinguish a deferred close (queued checks not yet
    # run — must NOT validate/merge yet) from a plain FinalAnswer. Race-free: it comes
    # from the fire itself, not from a disk read that may lag the process exit.
    ctx.http_post(
        f"/api/tickets/{slug}/{ticket_id}/completed",
        {"agent_id": ctx.self_id, "run_kind": ctx.run_kind, "close_reason": ctx.close_reason},
        timeout=1900,
    )


HOOK_DEFS = [
    HookDef(name="run_completion_chain", event="on_completion", func=run_completion_chain),
]
