# [desc] Tests that previous turn prose is excluded from next LLM call wire payload for minimal context
# <tool_use name="FinalAnswer" id="f1"><param name="answer">Tests that previous turn prose is excluded from next LLM call wire payload for minimal context</param></tool_use> [/desc]
"""Test that the wire payload stays minimal across turns.

Reproduces the issue: after a turn with long prose + housekeeping tool_calls
(Methodology, Snippet), the NEXT LLM call should NOT carry the previous
assistant's prose or tool_use XML on the wire — only the tool_results.
"""
import pytest
from tests.fake_llm import MockLLM
from tests.e2e_harness import bouzecode


LONG_PROSE = "A" * 2000  # Simulates a long explanation (~571 tokens)

TURN1_RESPONSE = (
    f"{LONG_PROSE}\n"
    '<tool_use name="Read" id="rd1">'
    '<param name="file_path">C:\\fake\\file.py</param>'
    "</tool_use>\n"
    '<tool_use name="Methodology" id="m1">'
    '<param name="content">Some methodology note</param>'
    "</tool_use>\n"
    '<tool_use name="Snippet" id="s1">'
    '<param name="file_path">C:\\fake\\file.py</param>'
    '<param name="ranges">[[1,10]]</param>'
    '<param name="label">test snippet</param>'
    "</tool_use>"
)

TURN2_RESPONSE = "Done. The task is complete."


def _count_fresh_tokens(messages: list[dict]) -> float:
    """Approximate token count from message content (chars / 3.5)."""
    total_chars = 0
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str):
            total_chars += len(content)
        elif isinstance(content, list):
            for block in content:
                total_chars += len(block.get("text", ""))
    return total_chars / 3.5


class TestMinimalWireFreshTokens:
    """The wire payload at turn 2 must NOT contain turn 1's prose."""

    def test_turn2_payload_excludes_previous_prose(self):
        """After turn 1 (long prose + Methodology + Snippet), turn 2's
        payload should not contain the 2000-char prose block."""
        mock = MockLLM([TURN1_RESPONSE, TURN2_RESPONSE])
        result = bouzecode(
            ["Explain the crash recovery system"],
            mock_llm=mock,
            mock_tools=True,
            config_overrides={"enforce_tests": False, "enforce_methodology": False},
        )
        assert mock.call_count == 2

        turn2_messages = mock.get_messages(1)
        turn2_text = " ".join(
            msg.get("content", "") if isinstance(msg.get("content"), str)
            else " ".join(b.get("text", "") for b in msg.get("content", []))
            for msg in turn2_messages
        )

        # The long prose from turn 1 must NOT appear in turn 2's payload
        assert LONG_PROSE not in turn2_text, (
            f"Turn 2 payload contains {len(LONG_PROSE)} chars of previous "
            f"prose that should have been dropped by minimal_payload"
        )

    def test_turn2_payload_contains_tool_results(self):
        """Turn 2's payload must contain the tool_results from turn 1."""
        mock = MockLLM([TURN1_RESPONSE, TURN2_RESPONSE])
        result = bouzecode(
            ["Explain the crash recovery system"],
            mock_llm=mock,
            mock_tools=True,
            config_overrides={"enforce_tests": False, "enforce_methodology": False},
        )
        turn2_messages = mock.get_messages(1)
        turn2_text = " ".join(
            msg.get("content", "") if isinstance(msg.get("content"), str)
            else " ".join(b.get("text", "") for b in msg.get("content", []))
            for msg in turn2_messages
        )

        # Tool results must be present (they carry useful info)
        assert "Methodology" in turn2_text or "executed" in turn2_text, (
            "Turn 2 payload is missing tool_results from turn 1"
        )

    def test_turn2_fresh_tokens_are_minimal(self):
        """Fresh tokens at turn 2 should be small (< 300 tokens).

        With the current bug, turn 2 carries ~2000 chars of prose =
        ~571 tokens. After fix, it should only have tool_results (~50 tokens).
        """
        mock = MockLLM([TURN1_RESPONSE, TURN2_RESPONSE])
        result = bouzecode(
            ["Explain the crash recovery system"],
            mock_llm=mock,
            mock_tools=True,
            config_overrides={"enforce_tests": False, "enforce_methodology": False},
        )
        turn2_messages = mock.get_messages(1)
        fresh = _count_fresh_tokens(turn2_messages)

        # After fix: only tool_results + user msg on wire < 300 tokens
        # Before fix: prose (571) + tool_use XML (200+) + tool_results (50) = 800+
        assert fresh < 300, (
            f"Turn 2 has {fresh:.0f} estimated fresh tokens — expected < 300. "
            f"The payload likely still contains previous prose/tool_use XML."
        )

    def test_turn2_excludes_tool_use_xml(self):
        """Turn 2 should not contain <tool_use> XML from turn 1's assistant."""
        mock = MockLLM([TURN1_RESPONSE, TURN2_RESPONSE])
        result = bouzecode(
            ["Explain the crash recovery system"],
            mock_llm=mock,
            mock_tools=True,
            config_overrides={"enforce_tests": False, "enforce_methodology": False},
        )
        turn2_messages = mock.get_messages(1)
        turn2_text = " ".join(
            msg.get("content", "") if isinstance(msg.get("content"), str)
            else " ".join(b.get("text", "") for b in msg.get("content", []))
            for msg in turn2_messages
        )

        # No tool_use XML from previous turn should appear
        assert '<tool_use name="Methodology"' not in turn2_text, (
            "Turn 2 payload contains <tool_use> XML from turn 1 — "
            "should be elided by minimal_payload"
        )
        assert '<tool_use name="Snippet"' not in turn2_text, (
            "Turn 2 payload contains <tool_use> XML from turn 1 — "
            "should be elided by minimal_payload"
        )
