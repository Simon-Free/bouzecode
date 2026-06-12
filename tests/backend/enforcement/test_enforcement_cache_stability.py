# [desc] Tests that enforcement retries send full tool_schemas without filtering, preserving Anthropic prompt cache. [/desc]
"""Enforcement retries must NOT filter tool_schemas.

When the model fails to emit Methodology/Snippet, the enforcement mechanism
retries with ctx.enforcement_retries > 0. Previously, this filtered
tool_schemas to only Methodology+Snippet, which changed the system block
content (tool_docs) and invalidated the Anthropic prompt cache (~7K tokens
lost per retry).

The fix: always send the full tool_schemas regardless of enforcement state.
The enforcement prompt message is sufficient to guide the model.
"""
from __future__ import annotations

import pytest

from bouzecode.backend.agent.state import AgentState
from bouzecode.backend.agent.loop_turn import stream_llm_turn
from bouzecode.backend.agent.loop_context import LoopContext
from bouzecode.backend.agent.providers.types import AssistantTurn, StreamStarted
from bouzecode.backend.core.tool_registry import get_tool_schemas


class TestEnforcementSchemaStability:
    """Verify tool_schemas are NOT filtered during enforcement retries."""

    def test_schemas_not_filtered_on_retry(self, monkeypatch):
        """When enforcement_retries > 0, stream() must receive full tool_schemas."""
        captured_schemas: list[list] = []

        def fake_stream(*, model, system, messages, tool_schemas, config):
            captured_schemas.append(list(tool_schemas))
            yield StreamStarted()
            yield AssistantTurn(
                text=".", tool_calls=[], in_tokens=100, out_tokens=10,
                cache_read_tokens=0, cache_creation_tokens=0, stop_reason="end_turn",
            )

        monkeypatch.setattr("bouzecode.backend.agent.loop_turn.stream", fake_stream)
        monkeypatch.setattr("bouzecode.backend.agent.loop_turn.dump_turn_payload", lambda *a, **kw: None)
        monkeypatch.setattr("bouzecode.backend.agent.loop_turn._build_messages_for_api", lambda s, c: list(s.messages))

        state = AgentState()
        state.messages = [{"role": "user", "content": "test"}]
        config = {"model": "test", "_context_state": state.context_state}

        ctx = LoopContext(max_nudges=3)
        ctx.enforcement_retries = 1  # Simulate enforcement retry

        # Consume the generator
        list(stream_llm_turn(state, config, "system", ctx, cancel_check=lambda: False))

        assert len(captured_schemas) == 1
        full_schemas = get_tool_schemas()
        assert captured_schemas[0] == full_schemas, (
            f"Expected full schemas ({len(full_schemas)} tools) but got "
            f"{len(captured_schemas[0])} tools — schemas were filtered!"
        )
        assert len(captured_schemas[0]) > 2, "Should have more than just Methodology+Snippet"

    def test_schemas_identical_between_normal_and_retry(self, monkeypatch):
        """Schemas on normal call vs enforcement retry must be identical."""
        captured_schemas: list[list] = []

        def fake_stream(*, model, system, messages, tool_schemas, config):
            captured_schemas.append(list(tool_schemas))
            yield StreamStarted()
            yield AssistantTurn(
                text=".", tool_calls=[], in_tokens=100, out_tokens=10,
                cache_read_tokens=0, cache_creation_tokens=0, stop_reason="end_turn",
            )

        monkeypatch.setattr("bouzecode.backend.agent.loop_turn.stream", fake_stream)
        monkeypatch.setattr("bouzecode.backend.agent.loop_turn.dump_turn_payload", lambda *a, **kw: None)
        monkeypatch.setattr("bouzecode.backend.agent.loop_turn._build_messages_for_api", lambda s, c: list(s.messages))

        state = AgentState()
        state.messages = [{"role": "user", "content": "test"}]
        config = {"model": "test", "_context_state": state.context_state}

        # Call 1: normal (enforcement_retries = 0)
        ctx1 = LoopContext(max_nudges=3)
        ctx1.enforcement_retries = 0
        list(stream_llm_turn(state, config, "system", ctx1, cancel_check=lambda: False))

        # Call 2: enforcement retry (enforcement_retries = 1)
        ctx2 = LoopContext(max_nudges=3)
        ctx2.enforcement_retries = 1
        list(stream_llm_turn(state, config, "system", ctx2, cancel_check=lambda: False))

        assert len(captured_schemas) == 2
        assert captured_schemas[0] == captured_schemas[1], (
            f"Schemas differ! Normal: {len(captured_schemas[0])} tools, "
            f"Retry: {len(captured_schemas[1])} tools"
        )
