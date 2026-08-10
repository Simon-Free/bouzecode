"""SPEC#1 — un agent tué par une panne API fatale doit poser close_reason='api_error'
sur l'AgentState avant que l'exception ne remonte (au lieu de sortir comme une fin normale).

On simule la panne via le hook provider PATCHABLE (set_stream_interceptor), PAS via
unittest.mock.patch : un stub streamer lève anthropic.APIConnectionError avant tout
event (exactement le cas des preuves : create() échoue 11× puis raise, 0 event streamé).
"""
from __future__ import annotations

import httpx
import pytest
import anthropic

from bouzecode.backend.agent.loop import run
from bouzecode.backend.agent.state import AgentState
from bouzecode.backend.agent.stream_interceptor import set_stream_interceptor


def _raising_streamer(_raw):
    def _stub(model, system, messages, tool_schemas, config):
        raise anthropic.APIConnectionError(
            message="Connection error.",
            request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"),
        )
        yield  # pragma: no cover — makes this a generator
    return _stub


def test_api_connection_error_sets_close_reason_api_error():
    set_stream_interceptor(_raising_streamer)
    try:
        state = AgentState()
        config = {
            "model": "claude-sonnet-4",
            "task_classification": False,
            "enforce_methodology": False,
            "recover_memory": False,
        }
        with pytest.raises(anthropic.APIConnectionError):
            list(run("hello", state, config, "SYSTEM", cancel_check=None))
        assert state.close_reason == "api_error", (
            f"attendu close_reason='api_error', obtenu {state.close_reason!r}"
        )
    finally:
        set_stream_interceptor(None)
