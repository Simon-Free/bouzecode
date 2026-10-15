# [desc] Rattrapage d'un Methodology oublié : variante mécanique par défaut (ligne écrite par le harnais, zéro appel LLM), variante LLM sur demande (`methodology_recovery`). [/desc]
"""Rapport docs/reduction_tokens §2.2 (correctifs point 4).

L'appel annexe de rattrapage (`methrec`) relit la note entière et la réflexion du tour : jusqu'à
124 k tokens pour écrire une note oubliée. La variante `methodology_recovery = "mecanique"`
écrit à la place une ligne `(note non écrite par le modèle) — outils : …`, sans appel LLM ;
l'avertissement d'enforcement (événement + message `role="enforcement"`) reste le même.
"""
from __future__ import annotations

from bouzecode.backend.agent.loop_detector import EnforcementWarning
from tests.e2e_harness import bouzecode
from tests.fake_llm import MockLLM


def _session(tmp_path, **config):
    oubli = {"thinking": ["je lance le test"], "text": (
        '<tool_use name="Bash" id="b1"><param name="command">echo hi</param></tool_use>'
        f'<tool_use name="Write" id="w1"><param name="file_path">{tmp_path / "app.js"}</param>'
        '<param name="content">x</param></tool_use>')}
    mock = MockLLM([oubli, "Fini."])
    result = bouzecode(["fais-le"], mock_llm=mock,
                       config_overrides={"recover_memory": True, "enforce_tests": False, **config})
    return result, mock


def _note(result) -> str:
    return result.state.context_state.notes.get("methodology", "")


def test_rattrapage_mecanique_par_defaut_ecrit_une_ligne_sans_appel_llm(tmp_path):
    """Défaut depuis l'A/B DeepSeek du 24/09 (réussite et oublis égaux, 0 token de rattrapage)."""
    result, mock = _session(tmp_path)

    assert mock.side_calls == 0, "aucun appel annexe"
    assert "(note non écrite par le modèle) — outils : Bash echo hi, Write app.js" in _note(result)
    assert any(isinstance(e, EnforcementWarning) for e in result.events), "l'avertissement reste"
    assert any(m.get("role") == "enforcement" for m in result.messages)


def test_rattrapage_llm_sur_demande(tmp_path):
    result, mock = _session(tmp_path, methodology_recovery="llm")

    assert mock.side_calls >= 1, "methodology_recovery='llm' : l'appel annexe de rattrapage part"
    assert "(note non écrite par le modèle)" not in _note(result)
