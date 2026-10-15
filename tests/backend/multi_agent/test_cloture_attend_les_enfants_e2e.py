# [desc] Un agent normal qui appelle FinalAnswer avec des sous-agents en fond encore actifs : le harnais les attend dès la 1re tentative (via la barre du TUI en interactif) et rend leurs rapports (le cas manager, inchangé, est dans test_enfants_vus_par_le_parent.py). [/desc]
"""Session B4 du 2026-10-14 (TUI) : trois enfants lancés en fond, puis FinalAnswer aussitôt
(« je reprendrai à la fin de chacun d'eux ») — refusé, puis trois CheckAgentResult(wait=true).
Un agent normal n'est jamais réveillé par ses enfants : le harnais attend pour lui.

La boucle du principal tourne pour de vrai sur un MockLLM ; les enfants sont de faux
`_agent_run` (même seam que test_en_process_execution.py) qui livrent après un court délai."""
from __future__ import annotations

import time

import pytest

from bouzecode.backend.agent.state import AgentState, TurnDone
from bouzecode.backend.multi_agent.en_process.registre import RegistreAgents
from tests.e2e_harness import bouzecode
from tests.fake_llm import MockLLM


def _enfant_lent(prompt, state, config, system_prompt, depth=0, cancel_check=None):
    """Un enfant qui travaille un instant puis livre son rapport."""
    state.messages.append({"role": "user", "content": prompt})
    yield TurnDone(10, 1)
    time.sleep(0.3)
    state.final_answer = f"rapport de « {prompt} »"


def _outil(nom: str, i: str, **params) -> str:
    corps = "".join(f'<param name="{k}">{v}</param>' for k, v in params.items())
    return f'<tool_use name="{nom}" id="{i}">{corps}</tool_use>'


def _conversation() -> MockLLM:
    """Le principal lance deux enfants en fond, puis clôt tout de suite — deux fois au plus."""
    return MockLLM([
        _outil("Agent", "a1", prompt="audit du module A", background="true") +
        _outil("Agent", "a2", prompt="audit du module B", background="true"),
        _outil("FinalAnswer", "f1", answer="Je reprendrai à la fin de chacun d'eux."),
        _outil("FinalAnswer", "f2", answer="Audits A et B intégrés."),
        "fin",
    ])


def _resultats_final_answer(result) -> list[str]:
    return [str(m.get("content", "")) for m in result.messages
            if m.get("role") == "tool" and m.get("name") == "FinalAnswer"]


@pytest.fixture
def enfants_lents(monkeypatch):
    monkeypatch.setattr("bouzecode.backend.multi_agent.task._agent_run", _enfant_lent)
    monkeypatch.setattr("bouzecode.backend.multi_agent.en_process.execution._sauver",
                        lambda fiche: None)


def test_tui_la_premiere_cloture_attend_les_enfants_dans_la_barre(enfants_lents):
    """TUI : au 1er FinalAnswer, le harnais attend les enfants PAR le crochet d'attente du REPL
    (la barre des sous-agents reste à l'écran) et rend leurs rapports ; le 2e FinalAnswer livre."""
    registre = RegistreAgents()
    registre.declarer_principal(AgentState(), "claude-opus-5")
    attentes_par_la_barre = []

    def crochet_attente(fini, outils):
        attentes_par_la_barre.append(outils)
        registre.attendre_changement(0.05)

    result = bouzecode(["Audite A et B."], mock_llm=_conversation(), config_overrides={
        "_tui_agents": registre, "_attente_lot": crochet_attente})

    premier, second = _resultats_final_answer(result)
    assert premier.startswith("CLÔTURE DIFFÉRÉE — 2 sous-agent(s)")
    assert "rapport de « audit du module A »" in premier
    assert "rapport de « audit du module B »" in premier
    assert attentes_par_la_barre
    assert second.startswith("Session closing")
    assert result.state.final_answer == "Audits A et B intégrés."


def test_hors_tui_la_premiere_cloture_attend_aussi_les_enfants(enfants_lents):
    """Non interactif (sous-agents en thread) : même règle, un seul tour de refus."""
    result = bouzecode(["Audite A et B."], mock_llm=_conversation())

    premier, _second = _resultats_final_answer(result)
    assert premier.startswith("CLÔTURE DIFFÉRÉE — 2 sous-agent(s)")
    assert "rapport de « audit du module B »" in premier
    assert result.state.final_answer == "Audits A et B intégrés."

