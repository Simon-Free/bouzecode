# [desc] E2E tests reproducing the truncated LLM stream bug where tool_calls are lost and agent stops [/desc]
"""E2E test: truncated stream (max_tokens) produces empty tool_calls and agent stops.

This reproduces the bug where the LLM hits max_tokens mid-response,
emitting only a trivial text (e.g. ".") without any tool_use XML.
The agent loop should detect this and auto-continue, but currently
it just breaks — leaving the user with a useless "." reply.

Bug reproduction from session_150842_a752a952.bak.json:
  - Assistant receives tool_results (RunPythonTest with 8 failures)
  - Assistant responds with content="." and tool_calls=[]
  - User has to manually say "Continue, les tools use n'ont pas été pris en compte"
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from tests.e2e_harness import bouzecode
from tests.fake_llm import MockLLM

METH_OPEN = '<tool_use name="Methodology" id="m1"><param name="content">'
METH_CLOSE = '</param></tool_use>'
METH = f'{METH_OPEN}test note{METH_CLOSE}'

BASH_OPEN = '<tool_use name="Bash" id="b1"><param name="command">'
BASH_CLOSE = '</param></tool_use>'
BASH_ECHO = f'{BASH_OPEN}echo hello{BASH_CLOSE}'

BASH2_OPEN = '<tool_use name="Bash" id="b2"><param name="command">'


class TestTruncatedStreamBug:
    """Reproduce: LLM truncated at max_tokens -> tool_calls lost -> agent stops."""

    def test_truncated_response_stops_agent(self):
        """Bug: after tool results, LLM emits just "." (truncated) and agent stops.

        This test demonstrates the current buggy behavior:
        - Turn 1: LLM emits Methodology + Bash tool call
        - Tool results come back
        - Turn 2: LLM emits just "." (simulating max_tokens truncation)
        - Agent STOPS (bug) instead of auto-continuing
        """
        mock = MockLLM([
            # Turn 1: normal response with Methodology + Bash
            f'{METH}\n{BASH_ECHO}',
            # Turn 2: truncated response — just "." (simulating max_tokens hit)
            ".",
        ])

        result = bouzecode(
            ["Fix the failing tests"],
            mock_llm=mock,
            mock_tools={"Bash": "hello\n"},
            config_overrides={"_enforce_tests": False},
        )

        # The agent stopped after "." — this is the BUG
        last_assistant = None
        for msg in reversed(result.messages):
            if msg["role"] == "assistant":
                last_assistant = msg
                break

        assert last_assistant is not None
        dot_msgs = [m for m in result.messages if m["role"] == "assistant" and m.get("content", "").strip() == "."]
        assert len(dot_msgs) >= 1, "Truncated '.' should be in assistant messages"
        assert dot_msgs[0]["tool_calls"] == []

        # 2 main LLM calls: normal + truncated. Methodology enforcement now runs
        # as a depth-1 recovery side-call, not an extra main turn (commit 697efcf).
        assert mock.call_index == 2

    def test_truncated_with_incomplete_tool_use_xml(self):
        """XML tool_use started but not closed (stream cut mid-tag).

        The parser's finalize() detects incomplete XML and produces an
        _XmlParseError tool_call. The loop handles this gracefully —
        the error is reported back and the LLM retries.
        """
        # Incomplete XML: stream cut mid-param value
        incomplete_xml = f'.\n{BASH2_OPEN}echo'

        mock = MockLLM([
            # Turn 1: normal
            f'{METH}\n{BASH_ECHO}',
            # Turn 2: incomplete XML (stream cut mid-tool_use)
            incomplete_xml,
            # Turn 3: enforcement/error retry — methodology only
            METH,
            # Turn 4: final text reply with Methodology (to avoid another enforcement cycle)
            "Done.",
        ])

        result = bouzecode(
            ["Run tests"],
            mock_llm=mock,
            mock_tools={"Bash": "hello\n"},
            config_overrides={"_enforce_tests": False},
        )

        # The incomplete XML was detected and the LLM retried
        # At least 3 calls happened (original + truncated + retry)
        assert mock.call_index >= 3

    def test_normal_empty_reply_is_valid_stop(self):
        """A normal empty reply (no truncation) is a valid stop condition.

        When the LLM intentionally replies with just text and no tools,
        that's a valid final answer — NOT a truncation bug.
        """
        mock = MockLLM([
            # Turn 1: normal response with tools
            f'{METH}\n{BASH_ECHO}',
            # Turn 2: intentional final text reply (no tool_use = conversation ends)
            "Done, all tests pass.",
        ])

        result = bouzecode(
            ["Run the tests"],
            mock_llm=mock,
            mock_tools={"Bash": "hello\n"},
            config_overrides={"_enforce_tests": False},
        )

        last_assistant = None
        for msg in reversed(result.messages):
            if msg["role"] == "assistant":
                last_assistant = msg
                break

        assert last_assistant is not None
        done_msgs = [m for m in result.messages if m["role"] == "assistant" and "Done" in m.get("content", "")]
        assert len(done_msgs) >= 1
        assert done_msgs[0]["tool_calls"] == []
        # 2 main LLM calls: normal + text-only stop. Methodology enforcement now
        # runs as a depth-1 recovery side-call, not an extra main turn (697efcf).
        assert mock.call_index == 2
