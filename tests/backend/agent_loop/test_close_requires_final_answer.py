# [desc] Tests that headless sessions require explicit FinalAnswer to close, with nudge mechanics and cap behavior. [/desc]
"""
close_requires_final_answer mode:
- Text-without-tools does NOT close in headless → nudge
- Meta-only + text does NOT close in headless → nudge
- FinalAnswer closes normally
- Cap: 4 nudges without productive tool call → force close (final_answer_never_called)
- Interactive (mode disabled): behaviour unchanged (text closes)
"""
from tests.e2e_harness import bouzecode
from tests.fake_llm import MockLLM

METH = '<tool_use name="Methodology" id="m1"><param name="content">todo</param></tool_use>'
FINAL = ('<tool_use name="FinalAnswer" id="f1">'
         '<param name="answer">Done.</param></tool_use>')
BASH = '<tool_use name="Bash" id="b1"><param name="command">echo ok</param></tool_use>'

# Config that activates final_answer mode (headless default when FinalAnswer present)
HEADLESS_CFG = {"close_requires_final_answer": True, "test_enforcement": False, "enforce_methodology": False}
# Config for interactive/legacy mode
LEGACY_CFG = {"close_requires_final_answer": False, "test_enforcement": False, "enforce_methodology": False}


def _user_msgs(result):
    return [str(m.get("content", "")) for m in result.messages if m.get("role") == "user"]


def _nudge_msgs(result):
    return [m for m in _user_msgs(result) if "FinalAnswer" in m and "System Automated" in m]


# --- (a) Headless: text-without-tools does NOT close, FinalAnswer closes ---

def test_headless_text_without_tools_does_not_close():
    """In headless mode, a plain text reply (no tools) nudges instead of closing."""
    mock = MockLLM([
        "Voilà ma réponse finale.",          # text only — should NOT close
        f"{METH}\n{FINAL}",                  # model calls FinalAnswer after nudge
    ])
    result = bouzecode(["fais le travail"], mock_llm=mock, config_overrides=HEADLESS_CFG)

    # Session should have ended via FinalAnswer, not text-only
    assert result.state.close_reason == "final_answer"
    assert result.state.final_answer == "Done."
    nudges = _nudge_msgs(result)
    assert len(nudges) >= 1, "Should have nudged to call FinalAnswer"


def test_headless_final_answer_closes():
    """FinalAnswer immediately closes the session in headless mode."""
    mock = MockLLM([f"{METH}\n{FINAL}", "NEVER CONSUMED"])
    result = bouzecode(["fais le travail"], mock_llm=mock, config_overrides=HEADLESS_CFG)

    assert result.state.close_reason == "final_answer"
    assert result.state.final_answer == "Done."


# --- (b) Meta-only + text does not close in headless ---

def test_headless_meta_only_with_text_does_not_close():
    """Text + Methodology only (no productive tools) nudges in headless mode."""
    mock = MockLLM([
        f"Voilà la réponse.\n{METH}",       # text + meta only — should NOT close
        f"{METH}\n{FINAL}",                  # model calls FinalAnswer after nudge
    ])
    result = bouzecode(["question"], mock_llm=mock, config_overrides=HEADLESS_CFG)

    assert result.state.close_reason == "final_answer"
    nudges = _nudge_msgs(result)
    assert len(nudges) >= 1


# --- (c) Cap: final_answer_never_called terminates ---

def test_headless_cap_final_answer_never_called():
    """After 4 consecutive nudges without productive calls, force close."""
    # Model keeps replying with text only, never calls FinalAnswer.
    # 4 nudges = 5 responses consumed (nudge after each of 1-4, 5th triggers cap).
    mock = MockLLM([
        "réponse 1",
        "réponse 2",
        "réponse 3",
        "réponse 4",
        "réponse 5",  # consumed — triggers the cap check
        "réponse 6",  # should NOT be consumed
    ])
    result = bouzecode(["fais le travail"], mock_llm=mock, config_overrides=HEADLESS_CFG)

    assert result.state.close_reason == "final_answer_never_called"
    # Should have sent 4 nudges before force-closing on the 5th text reply
    nudges = _nudge_msgs(result)
    assert len(nudges) == 4


# --- (e) Interactive/legacy: text closes normally (unchanged) ---

def test_legacy_text_without_tools_closes():
    """In legacy mode, text-only reply closes the session as before."""
    mock = MockLLM(["Voilà ma réponse finale.", "NEVER CONSUMED"])
    result = bouzecode(["question simple"], mock_llm=mock, config_overrides=LEGACY_CFG)

    # Should close on text without needing FinalAnswer
    assert result.state.close_reason != "final_answer"
    assert "no_tools_text" in (result.state.close_reason or "")


# --- Regression: productive work + FinalAnswer ---

def test_headless_productive_then_final_answer():
    """Productive work followed by FinalAnswer closes cleanly."""
    mock = MockLLM([
        f"{METH}\n{BASH}",                  # productive work
        f"{METH}\n{FINAL}",                 # close
    ])
    result = bouzecode(["fais le travail"], mock_llm=mock, config_overrides=HEADLESS_CFG)

    assert result.state.close_reason == "final_answer"
    assert result.state.final_answer == "Done."
