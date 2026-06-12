# [desc] E2E tests verifying Methodology tool captures content, accumulates across turns, and auto-appends user messages
# <tool_use name="FinalAnswer" id="r1"><param name="answer">E2E tests verifying Methodology tool captures content, accumulates across turns, and auto-appends user messages</param></tool_use> [/desc]
"""Methodology tool behaviour through real bouzecode() conversations.

Replaces the direct methodology_tool(...) / append_*_to_methodology(...) unit tests:
the (mocked) model calls Methodology and we assert on the resulting methodology note
(result.state.context_state.notes). The note also auto-captures the user message and
answered AskUserQuestion blocks, which we exercise here too.

(The "## Plan @" auto-append is driven by plan mode → covered in the plan_mode cluster.
 methodology_tool's no-context-state error path cannot occur in a real conversation,
 where the loop always wires config["_context_state"].)
"""
from __future__ import annotations

from tests.e2e_harness import bouzecode
from tests.fake_llm import MockLLM
from bouzecode.backend.context_manager import METHODOLOGY_NOTE


def _meth(content):
    return f'done.\n<tool_use name="Methodology" id="m1"><param name="content">{content}</param></tool_use>'


def _note(result):
    return result.state.context_state.notes.get(METHODOLOGY_NOTE, "")


def test_methodology_content_lands_in_note():
    result = bouzecode(["do X"], mock_llm=MockLLM([_meth("first finding")]))
    assert "first finding" in _note(result)


def test_methodology_accumulates_across_turns():
    mock = MockLLM([_meth("## Goal\nfix bug"), _meth("## Findings\nin foo()")])
    note = _note(bouzecode(["t1", "t2"], mock_llm=mock))
    assert "## Goal" in note and "## Findings" in note


def test_methodology_empty_content_leaves_prior_intact():
    mock = MockLLM([_meth("important note"), _meth("")])
    note = _note(bouzecode(["t1", "t2"], mock_llm=mock))
    assert "important note" in note


def test_user_messages_auto_appended_as_blocks():
    mock = MockLLM([_meth("ok"), _meth("ok")])
    note = _note(bouzecode(["first ask", "second ask"], mock_llm=mock))
    assert note.count("## User @") == 2
    assert "first ask" in note and "second ask" in note


def test_snippet_block_lands_in_note(tmp_path):
    f = tmp_path / "f.py"
    f.write_text("import os\nx = 1\n", encoding="utf-8")
    snip = (f'<tool_use name="Snippet" id="s1"><param name="file_path">{f}</param>'
            f'<param name="ranges">[[1, 1]]</param><param name="label">imp</param></tool_use>')
    mock = MockLLM([f'{_meth("ok")}\n{snip}'])
    note = _note(bouzecode(["snip"], mock_llm=mock))
    assert "import os" in note   # frozen snippet block lands in the note

# NOTE: the "## Q&A @" auto-append on AskUserQuestion is intentionally not asserted
# here — in the harness flow PausedForInput.question is empty, so
# append_ask_user_question_to_methodology() short-circuits on `if not question`.
# Whether that is a real gap (Q&A never recorded in some flows) or only a harness
# limitation is left for the AskUserQuestion/interaction investigation.
