# [desc] Tests for plan auto-validator: verdict parsing, override logic, and state integration
# <tool_use name="FinalAnswer" id="x1"><param name="answer">Tests for plan auto-validator: verdict parsing, override logic, and state integration</param></tool_use> [/desc]
"""Tests for plan_auto_validator — new architecture with full context."""
from bouzecode.backend.tools.plan_auto_validator import _parse_verdict, validate_plan_auto, VALIDATOR_INSTRUCTIONS_SEPARATOR


class TestParseVerdict:
    def test_approve_true(self):
        assert _parse_verdict("<approve>true</approve>") == (True, "")

    def test_approve_false_with_feedback(self):
        resp = "<approve>false</approve>\n<feedback>No tests</feedback>"
        approved, feedback = _parse_verdict(resp)
        assert approved is False
        assert "No tests" in feedback

    def test_legacy_approved(self):
        assert _parse_verdict("<decision>approved</decision>") == (True, "")

    def test_legacy_rejected(self):
        resp = "<decision>rejected</decision>\n<justification>Bad plan</justification>"
        approved, feedback = _parse_verdict(resp)
        assert approved is False
        assert "Bad plan" in feedback

    def test_no_valid_tag_rejects(self):
        approved, feedback = _parse_verdict("Le plan est validé. J'implémente...")
        assert approved is False
        assert "did not contain a valid" in feedback

    def test_thinking_stripped(self):
        resp = "<thinking>blah blah</thinking>\n<approve>true</approve>"
        assert _parse_verdict(resp) == (True, "")


class TestValidatePlanAutoOverride:
    def test_override_approved(self):
        config = {"_plan_auto_validate_result": (True, "")}
        assert validate_plan_auto("any plan", config) == (True, "")

    def test_override_rejected(self):
        config = {"_plan_auto_validate_result": (False, "nope")}
        assert validate_plan_auto("any plan", config) == (False, "nope")


class TestValidatePlanAutoWithState:
    """Test that validate_plan_auto uses state.last_api_payload when available."""

    def test_uses_last_api_payload(self):
        class FakeState:
            last_api_payload = [
                {"role": "user", "content": "Build me a CLI tool"},
            ]

        config = {
            "_state": FakeState(),
            "_system_prompt": "You are a helpful assistant.",
            "_plan_auto_validate_result": (True, ""),
        }
        result = validate_plan_auto("# My Plan\n## Tests\n...", config)
        assert result == (True, "")

    def test_fallback_without_state(self):
        from bouzecode.backend.context_manager.state import ContextState
        gc = ContextState(notes={"methodology": "some context"})
        config = {
            "_context_state": gc,
            "_plan_auto_validate_result": (True, ""),
        }
        result = validate_plan_auto("# Plan content", config)
        assert result == (True, "")


class TestValidatorInstructionsSeparator:
    def test_separator_is_visible(self):
        assert len(VALIDATOR_INSTRUCTIONS_SEPARATOR) >= 40
        assert "=" in VALIDATOR_INSTRUCTIONS_SEPARATOR
