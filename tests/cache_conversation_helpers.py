# [desc] Helpers for live-API integration tests: credential gating, socle probes, and dispatch wrappers. [/desc]
from __future__ import annotations

import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# Force UTF-8 for stdout/stderr so test output can print the warning glyphs
# (e.g. '⚠') emitted by providers/backends/anthropic_stream.py.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from bouzecode.backend.agent.providers.backends.dispatch import stream
from bouzecode.backend.agent.providers.types import AssistantTurn
from bouzecode.backend.core.tool_registry import get_tool_schemas


# Flipped to True by require_api_key() once credentials are confirmed; the
# conftest network guard reads this to allow the live socle call for this test
# only. Reset to False before every test by the autouse guard fixture.
LIVE_API_ALLOWED = False


_SOCLE_REACHABLE: bool | None = None  # probed once per session


def _socle_reachable() -> bool:
    """One TCP probe of the socle host: credentials can be present while the
    machine is off the SNCF VPN (evenings) — live tests must skip, not fail."""
    global _SOCLE_REACHABLE
    if _SOCLE_REACHABLE is None:
        import socket
        from urllib.parse import urlparse
        base_url = os.environ.get("ANTHROPIC_BASE_URL", "")
        host = urlparse(base_url).hostname if base_url else "api.anthropic.com"
        try:
            socket.create_connection((host, 443), timeout=3).close()
            _SOCLE_REACHABLE = True
        except OSError:
            _SOCLE_REACHABLE = False
    return _SOCLE_REACHABLE


def require_api_key() -> None:
    """Skip the test when no socle credentials are present or the socle is
    unreachable (off VPN); otherwise opt this test in to the live LLM (lets the
    conftest network guard through)."""
    global LIVE_API_ALLOWED
    if not os.environ.get("ANTHROPIC_API_KEY"):
        pytest.skip("ANTHROPIC_API_KEY not set — live integration test")
    if not _socle_reachable():
        pytest.skip("socle unreachable (off VPN) — live integration test")
    LIVE_API_ALLOWED = True


def wait_mcp_ready() -> None:
    """No-op — MCP module removed."""
    pass


def dump_system_blocks(label: str) -> None:
    """Rebuild the same system_blocks dispatch.stream would send and log sizes."""
    from bouzecode.backend.xml_tool_protocol import build_tool_docs
    from bouzecode.backend.core.context import build_system_prompt_parts
    stable_prefix, volatile = build_system_prompt_parts({})
    tool_docs = build_tool_docs(get_tool_schemas() or [])
    print(
        f"[{label}] system-block chars: "
        f"stable={len(stable_prefix):,} "
        f"tool_docs={len(tool_docs):,} "
        f"volatile={len(volatile):,} "
        f"tool_count={len(get_tool_schemas() or [])}"
    )


def run_turn_via_dispatch(model: str, messages: list, config: dict) -> AssistantTurn:
    final = None
    for event in stream(
        model=model,
        system="",
        messages=messages,
        tool_schemas=get_tool_schemas(),
        config=config,
    ):
        if isinstance(event, AssistantTurn):
            final = event
    assert final is not None, "dispatch.stream yielded no AssistantTurn"
    return final


def call_anthropic_direct(model: str, system_blocks: list, user_msg: str, *, max_tokens: int = 32) -> AssistantTurn:
    from bouzecode.backend.agent.providers.backends.anthropic_stream import stream_anthropic
    turn = None
    for event in stream_anthropic(
        os.environ["ANTHROPIC_API_KEY"],
        model,
        system_blocks,
        [{"role": "user", "content": user_msg}],
        [],
        {"max_tokens": max_tokens},
        base_url=os.environ.get("ANTHROPIC_BASE_URL"),
    ):
        if isinstance(event, AssistantTurn):
            turn = event
    assert turn is not None
    return turn
