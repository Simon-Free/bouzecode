# [desc] Un fil qui finit sur un tool_result, sans message user : l'inventaire du harnais part quand même, en <harness_notes> APRÈS le résultat, qui reste intact. [/desc]
"""Regression (session 76a7d766, T71): the per-iteration audit note MUST land even when the
wire ends on a tool_result with no plain user message. It used to be prepended INTO that
tool_result (`_inject_into_last_user_message`); since 2026-10-07 harness text inside tool
data is banned (content_filter refusals of claude-opus-5-5 on the gateway), so it rides in a
<harness_notes> user message placed right after the results."""
from bouzecode.backend.agent.providers.backends.dispatch import stream
from bouzecode.backend.agent.providers.types import SystemPayload

READ = {"name": "Read", "description": "Read a file.",
        "input_schema": {"type": "object", "properties": {"file_path": {"type": "string"}}}}
WIRE = [
    {"role": "assistant", "content": ".", "tool_calls": [
        {"id": "b1", "name": "Read", "input": {"file_path": "log.txt"}}]},
    {"role": "tool", "tool_call_id": "b1", "name": "Read", "content": "git log output"},
]


def test_audit_lands_after_a_trailing_tool_result(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    generator = stream("claude-sonnet-4-6", "system", WIRE, [READ], {})
    payload = next(generator)
    generator.close()
    assert isinstance(payload, SystemPayload)
    tool, notes = payload.messages[-2:]
    assert tool["role"] == "tool" and tool["content"] == "git log output"
    assert notes["role"] == "user" and notes["content"].startswith("<harness_notes>")
    assert "b1 (Read log.txt)" in notes["content"]
