# [desc] E2E (mock_llm): Bash(deferred=True) empile sans executer ; FinalAnswer leve DeferredChecks. [/desc]
"""Flux deferred au niveau conversation (LLM mocke, pas d'appel reseau).

Couvre la moitie 'boucle agent' du mecanisme : un Bash(deferred=True) passe par
le vrai pipeline d'outils (enqueue, n'execute pas), puis FinalAnswer avec une file
non vide leve DeferredChecks portant answer + checks. Le drain/runner (moitie web)
est couvert par tests/.../test_deferred.py + la validation live.
"""
import pytest

from tests.e2e_harness import bouzecode
from tests.fake_llm import MockLLM
from bouzecode.backend.tools.interaction import DeferredChecks

METH = '<tool_use name="Methodology" id="m1"><param name="content">ok</param></tool_use>'


def test_deferred_bash_enqueues_then_finalanswer_raises():
    """Bash(deferred=True) n'execute pas (enqueue) ; FinalAnswer avec file non vide
    leve DeferredChecks(answer, checks) — le contrat consomme par le runner."""
    mock = MockLLM([
        f'{METH}\n<tool_use name="Bash" id="b1"><param name="command">echo hi</param>'
        f'<param name="deferred">true</param></tool_use>',
        f'{METH}\n<tool_use name="FinalAnswer" id="f1"><param name="answer">livrable</param></tool_use>',
    ])
    with pytest.raises(DeferredChecks) as exc:
        bouzecode(["valide le deferred"], mock_llm=mock)
    assert exc.value.answer == "livrable"
    assert len(exc.value.checks) == 1
    assert exc.value.checks[0]["command"] == "echo hi"
    assert "timeout" in exc.value.checks[0]


def test_bash_without_deferred_does_not_raise():
    """Sanity (cas negatif) : Bash sans deferred -> file vide -> cloture normale,
    PAS de DeferredChecks (ne casse pas les sessions ordinaires)."""
    mock = MockLLM([
        f'{METH}\n<tool_use name="Bash" id="b1"><param name="command">echo hi</param></tool_use>',
        # Plain text, no tool call — that is what closes a session. A
        # Methodology-only batch is bookkeeping and earns a continue-nudge.
        "C'est fait.",
    ])
    result = bouzecode(["pas de deferred"], mock_llm=mock)
    assert result is not None
