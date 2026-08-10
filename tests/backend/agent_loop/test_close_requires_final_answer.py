# [desc] Tests that close_requires_final_answer mode enforces explicit FinalAnswer closure in headless sessions. [/desc]
"""
close_requires_final_answer mode:
- Text-without-tools does NOT close in headless → nudge
- Meta-only + text does NOT close in headless → nudge
- FinalAnswer closes normally
- Cap: 4 nudges without productive tool call → force close (final_answer_never_called)
- Interactive (mode disabled): behaviour unchanged (text closes)
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

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
    """After MAX_FA_NUDGES (10) consecutive nudges without productive calls, force close.
    Plafond relevé de 4→10 : on tolère une longue phase plan/implémentation avant de clore
    de force (sinon les grosses tâches étaient coupées prématurément, cf. RENDER)."""
    # Model keeps replying with text only, never calls FinalAnswer.
    # 10 nudges = 11 responses consumed (nudge after each of 1-10, 11th triggers cap).
    mock = MockLLM([f"réponse {i}" for i in range(1, 12)] + ["NON CONSOMMÉE"])
    result = bouzecode(["fais le travail"], mock_llm=mock, config_overrides=HEADLESS_CFG)

    assert result.state.close_reason == "final_answer_never_called"
    nudges = _nudge_msgs(result)
    assert len(nudges) == 10


def test_headless_thinking_only_nudges_to_implement_not_close():
    """FIX RENDER : un tour de PLANIFICATION (thinking, sans tool ni texte final) ne doit PAS
    être coercé vers FinalAnswer — il est poussé à CONTINUER l'implémentation. Sinon les grosses
    tâches (phase plan longue) livraient un diff VIDE."""
    mock = MockLLM([
        # tour de PLANIFICATION : thinking réel, aucun texte final, aucun tool
        {"thinking": ["Je planifie : éditer message_view.py puis tester."],
         "text": "", "stop_reason": "end_turn"},
        f"{BASH}",             # après le nudge, il AGIT (implémente)
        f"{METH}\n{FINAL}",    # puis clôt proprement
    ])
    result = bouzecode(["grosse tâche"], mock_llm=mock, config_overrides=HEADLESS_CFG)

    assert result.state.close_reason == "final_answer"          # a bien fini, pas coupé
    impl_nudges = [m for m in _user_msgs(result)
                   if "System Automated" in m and "implémente" in m.lower()]
    assert impl_nudges, "un tour thinking-only doit être poussé à continuer, pas à clore"


# --- (e) Interactive/legacy: text closes normally (unchanged) ---

def test_legacy_text_without_tools_closes():
    """In legacy mode, text-only reply closes the session as before."""
    mock = MockLLM(["Voilà ma réponse finale.", "NEVER CONSUMED"])
    result = bouzecode(["question simple"], mock_llm=mock, config_overrides=LEGACY_CFG)

    # Should close on text without needing FinalAnswer
    assert result.state.close_reason != "final_answer"
    assert "text_no_tools" in (result.state.close_reason or "")


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
