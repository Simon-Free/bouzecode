# [desc] Tests that methodology-only turns trigger continuation nudges and don't prematurely close the agent loop. [/desc]
"""Regression for the premature-stop bug: a model that records its plan in a
Methodology-only batch (no visible text) intended to keep working — the loop
used to BREAK there, killing the task after the plan."""
from tests.e2e_harness import bouzecode
from tests.fake_llm import MockLLM

METH = '<tool_use name="Methodology" id="m1"><param name="content">plan</param></tool_use>'
BASH = '<tool_use name="Bash" id="b1"><param name="command">echo travail</param></tool_use>'
NO_TEST_ENFORCE = {"test_enforcement": False}

CONTINUE_MARKER = "ni travail ni réponse finale"


def _continue_nudges(result):
    return [m for m in result.messages
            if m.get("role") == "user" and CONTINUE_MARKER in str(m.get("content", ""))]


def test_silent_methodology_only_turn_continues():
    """Plan-only turn (no text) → loop nudges and the model keeps working."""
    mock = MockLLM([
        METH,                       # silent plan: would previously end the session
        f"{METH}\n{BASH}",          # model resumes real work after the nudge
        f"fini.\n{METH}",           # closing turn with final text
    ])
    result = bouzecode(["fais la tâche"], mock_llm=mock, config_overrides=NO_TEST_ENFORCE)

    assert len(_continue_nudges(result)) == 1
    bash_results = [m for m in result.messages
                    if m.get("role") == "tool" and m.get("name") == "Bash"]
    assert bash_results, "work after the nudge must have executed"


def test_methodology_only_with_final_text_still_ends():
    """Final answer text + Methodology in the same batch = legitimate close."""
    mock = MockLLM([f"Voilà la réponse finale.\n{METH}"])
    result = bouzecode(["question simple"], mock_llm=mock, config_overrides=NO_TEST_ENFORCE)

    assert not _continue_nudges(result)
    assert result.messages[-1]["role"] != "user"


def test_three_consecutive_silent_meta_turns_terminate():
    """A model stuck on plan-only turns is nudged twice, then the session ends."""
    mock = MockLLM([METH, METH, METH, METH])
    result = bouzecode(["fais la tâche"], mock_llm=mock, config_overrides=NO_TEST_ENFORCE)

    assert len(_continue_nudges(result)) == 2


def test_native_mode_text_does_not_close_meta_only_turn():
    """Native tool-calling models (deepseek) narrate intent as visible text every
    turn — text must NOT close a meta-only batch there (observed live: a session
    died on '…puis écrivons le code'). The protocol-native close is a reply
    without tool calls (which still gets its one Methodology compliance turn)."""
    mock = MockLLM([
        f"Je comprends la structure, écrivons le code.\n{METH}",  # narration + meta-only
        f"{METH}\n{BASH}",                                        # resumes real work
        "Tout est terminé, voilà ma réponse finale.",             # no tools → close path
        METH,                                                     # forced compliance turn
    ])
    result = bouzecode(["fais la tâche"], mock_llm=mock,
                       config_overrides={"model": "deepseek-v4-flash",
                                         "test_enforcement": False})

    assert len(_continue_nudges(result)) == 1
    bash_results = [m for m in result.messages
                    if m.get("role") == "tool" and m.get("name") == "Bash"]
    assert bash_results, "work after the nudge must have executed"


def test_work_turn_resets_consecutive_meta_counter():
    """Silent plan turns separated by real work each get their own nudge."""
    mock = MockLLM([
        METH,                # nudge 1
        f"{METH}\n{BASH}",   # real work resets the counter
        METH,                # nudge again (would BREAK if the counter were global)
        f"fini.\n{METH}",
    ])
    result = bouzecode(["fais la tâche"], mock_llm=mock, config_overrides=NO_TEST_ENFORCE)

    assert len(_continue_nudges(result)) == 2
    closing = [m for m in result.messages
               if m.get("role") == "assistant" and "fini." in str(m.get("content", ""))]
    assert closing, "the final-text turn must have been reached"
