# [desc] Tests plan auto-validator XML verdict parsing and validate_plan_auto integration with monkeypatched LLM stream
# <tool_use name="FinalAnswer" id="x1"><param name="answer">Tests plan auto-validator XML verdict parsing and validate_plan_auto integration with monkeypatched LLM stream</param></tool_use> [/desc]
"""Tests that validate_plan_auto correctly parses XML decisions.

Monkeypatches providers.stream to return controlled responses.
Tests the real validate_plan_auto() function — the public entry point.
"""
from pathlib import Path

import pytest

from bouzecode.backend.context_manager.state import ContextState
import bouzecode.backend.agent.providers as providers
from bouzecode.backend.tools.plan_auto_validator import validate_plan_auto, _parse_verdict


def _make_stream(text):
    """Create a fake providers.stream generator that yields a single TextChunk."""
    def fake_stream(model, system, messages, tool_schemas, config):
        yield providers.TextChunk(text)
    return fake_stream


def make_config(tmp_path, methodology=""):
    """Build a minimal config dict."""
    import os
    os.chdir(tmp_path)
    context_state = ContextState()
    if methodology:
        context_state.notes["methodology"] = methodology
    return {
        "model": "sonnet",
        "_context_state": context_state,
        "_session_id": "test-session",
    }


# --- Unit tests for _parse_verdict (parsing logic) ---

class TestParseVerdict:
    def test_approved_simple(self):
        resp = "<decision>approved</decision><justification>All criteria met.</justification>"
        approved, feedback = _parse_verdict(resp)
        assert approved is True
        assert feedback == ""

    def test_rejected_with_justification(self):
        resp = "<decision>rejected</decision><justification>No tests described.</justification>"
        approved, feedback = _parse_verdict(resp)
        assert approved is False
        assert "No tests described" in feedback

    def test_rejected_without_justification(self):
        resp = "<decision>rejected</decision>"
        approved, feedback = _parse_verdict(resp)
        assert approved is False
        assert "no justification provided" in feedback.lower()

    def test_malformed_no_xml_rejects_by_default(self):
        resp = "This plan looks good to me! APPROVED!"
        approved, feedback = _parse_verdict(resp)
        assert approved is False
        assert "valid <approve> or <decision> tag" in feedback

    def test_case_insensitive(self):
        resp = "<decision>APPROVED</decision><justification>Looks great.</justification>"
        approved, feedback = _parse_verdict(resp)
        assert approved is True

    def test_thinking_tags_stripped(self):
        resp = "<thinking>Let me analyze...</thinking><decision>approved</decision><justification>OK</justification>"
        approved, feedback = _parse_verdict(resp)
        assert approved is True

    def test_emoji_in_justification_does_not_affect_decision(self):
        """Regression: old parser detected emoji anywhere → false reject."""
        resp = "<decision>approved</decision><justification>All ❌ issues resolved, tests ✅ present.</justification>"
        approved, feedback = _parse_verdict(resp)
        assert approved is True

    def test_whitespace_in_decision_tag(self):
        resp = "<decision> approved </decision><justification>Fine.</justification>"
        approved, feedback = _parse_verdict(resp)
        assert approved is True

    def test_justification_truncated_at_500(self):
        long_text = "x" * 600
        resp = f"<decision>rejected</decision><justification>{long_text}</justification>"
        approved, feedback = _parse_verdict(resp)
        assert approved is False
        assert len(feedback) == 500


# --- Integration tests for validate_plan_auto (with monkeypatch) ---

class TestValidatePlanAuto:
    def test_approved_plan(self, tmp_path, monkeypatch):
        config = make_config(tmp_path)
        monkeypatch.setattr(
            providers, "stream",
            _make_stream("<decision>approved</decision><justification>Complete plan with proper tests.</justification>"),
        )
        approved, feedback = validate_plan_auto("Some good plan content", config)
        assert approved is True
        assert feedback == ""

    def test_rejected_plan(self, tmp_path, monkeypatch):
        config = make_config(tmp_path)
        monkeypatch.setattr(
            providers, "stream",
            _make_stream("<decision>rejected</decision><justification>Missing test-first approach for bug fix.</justification>"),
        )
        approved, feedback = validate_plan_auto("Some bad plan", config)
        assert approved is False
        assert "test-first" in feedback.lower()

    def test_malformed_response_rejects(self, tmp_path, monkeypatch):
        """If LLM doesn't produce XML, plan is rejected (intransigent default)."""
        config = make_config(tmp_path)
        monkeypatch.setattr(
            providers, "stream",
            _make_stream("Hmm this plan seems fine, I'll approve it."),
        )
        approved, feedback = validate_plan_auto("Whatever", config)
        assert approved is False

    def test_methodology_passed_to_llm(self, tmp_path, monkeypatch):
        """Verify that methodology context is sent to the validator LLM."""
        captured = {}

        def capturing_stream(model, system, messages, tool_schemas, config):
            captured["messages"] = messages
            yield providers.TextChunk("<decision>approved</decision><justification>OK</justification>")

        config = make_config(tmp_path, methodology="Bug found in auth.py")
        monkeypatch.setattr(providers, "stream", capturing_stream)
        validate_plan_auto("Fix the bug", config)
        assert "Bug found in auth.py" in captured["messages"][0]["content"]
