# [desc] Clôture pilotée par la config : outils à effet sans enjeu de lecture, préfixes d'échec propres à l'agent. [/desc]
"""Deux clés de config que l'agent hôte (Focus) fournit au garde de clôture.

Audit des sessions Focus (30 jours, 2026-09-29) : 59 refus « MÊME lot » portaient sur
un outil à effet RÉUSSI (generate_csv, write_skill, store_dsm…) — le modèle a ré-émis
chaque fois la même réponse, un tour stérile. Et les outils Focus signalent leurs
échecs par « Erreur : … », que le garde ne reconnaissait pas : un `update_doc`
introuvable recevait l'avis « même lot » au lieu de l'avis « outil en échec ».

- `close_ok_tools` : outils dont le résultat RÉUSSI ne peut contredire la réponse ;
- `close_failure_prefixes` : débuts de résultat qui, pour cet agent, signent un échec.
Sans ces clés, le comportement des autres agents ne change pas.
"""
from __future__ import annotations

import pytest

from bouzecode.backend.core.tool_registry import (
    ToolDef, enable_tool, get_tool, register_tool, unregister_tool,
)
from tests.e2e_harness import bouzecode
from tests.fake_llm import MockLLM

METH = '<tool_use name="Methodology" id="m1"><param name="content">ok</param></tool_use>'
ANSWER = "Le CSV des ventes est prêt."
FINAL = f'<tool_use name="final_answer" id="f1"><param name="answer">{ANSWER}</param></tool_use>'
CSV = '<tool_use name="generate_csv" id="c1"><param name="name">ventes</param></tool_use>'
SQL = '<tool_use name="execute_sql" id="s1"><param name="query">select 1</param></tool_use>'

CSV_OK = "CSV ventes.csv généré (120 lignes)."
CSV_KO = "Erreur : aucune donnée pour la requête 'ventes'."
CONFIG_FOCUS = {"close_ok_tools": ["generate_csv"], "close_failure_prefixes": ["Erreur :"]}

_MARQUE = "ta clôture n'a PAS été acceptée"


def _outil(nom: str, reponses: dict, ends_turn: bool = False) -> ToolDef:
    return ToolDef(name=nom, ends_turn=ends_turn,
                   schema={"name": nom, "description": nom,
                           "input_schema": {"type": "object", "properties": {}}},
                   func=lambda p, c: reponses[nom] if nom in reponses else p.get("answer", ""))


@pytest.fixture
def outils_focus():
    """Trois outils à la Focus : une clôture `final_answer`, un effet, une requête."""
    reponses = {"generate_csv": CSV_OK, "execute_sql": "1 ligne : 1"}
    noms = ("generate_csv", "execute_sql", "final_answer")
    anciens = {nom: get_tool(nom) for nom in noms}
    for nom in noms:
        register_tool(_outil(nom, reponses, ends_turn=nom == "final_answer"))
        enable_tool(nom)
    yield reponses
    for nom, ancien in anciens.items():
        if ancien is None:
            unregister_tool(nom)
        else:
            register_tool(ancien)


def _refus(result) -> list[str]:
    return [_MARQUE + str(m.get("content", "")).split(_MARQUE, 1)[1] for m in result.messages
            if _MARQUE in str(m.get("content", ""))]


def test_un_effet_reussi_de_la_liste_ne_retient_pas_la_cloture(outils_focus):
    mock = MockLLM([f"{METH}\n{CSV}\n{FINAL}", "JAMAIS CONSOMMÉ"])
    result = bouzecode(["exporte les ventes"], mock_llm=mock, config_overrides=CONFIG_FOCUS)

    assert _refus(result) == []
    assert result.state.close_reason == "ends_turn_tool"
    assert len(mock.recorded_calls) == 1


def test_sans_la_cle_le_meme_effet_retient_toujours_la_cloture(outils_focus):
    mock = MockLLM([f"{METH}\n{CSV}\n{FINAL}", f"{METH}\n{FINAL}"])
    result = bouzecode(["exporte les ventes"], mock_llm=mock)

    refus = _refus(result)
    assert len(refus) == 1
    assert "MÊME lot" in refus[0]


def test_un_effet_de_la_liste_en_erreur_recoit_l_avis_outil_en_echec(outils_focus):
    outils_focus["generate_csv"] = CSV_KO
    mock = MockLLM([f"{METH}\n{CSV}\n{FINAL}", f"{METH}\n{FINAL}"])
    result = bouzecode(["exporte les ventes"], mock_llm=mock, config_overrides=CONFIG_FOCUS)

    refus = _refus(result)
    assert len(refus) == 1
    assert "n'a pas fait son travail" in refus[0]
    assert "generate_csv : Erreur : aucune donnée" in refus[0]


def test_un_outil_de_donnees_retient_la_cloture_meme_avec_la_cle(outils_focus):
    mock = MockLLM([f"{METH}\n{SQL}\n{FINAL}", f"{METH}\n{FINAL}"])
    result = bouzecode(["compte les ventes"], mock_llm=mock, config_overrides=CONFIG_FOCUS)

    refus = _refus(result)
    assert len(refus) == 1
    assert "MÊME lot que : execute_sql" in refus[0]


def test_une_trace_python_n_est_pas_un_effet_reussi(outils_focus):
    outils_focus["generate_csv"] = ("Traceback (most recent call last):\n"
                                    "  File \"x.py\", line 1\nKeyError: 'ventes'")
    mock = MockLLM([f"{METH}\n{CSV}\n{FINAL}", f"{METH}\n{FINAL}"])
    result = bouzecode(["exporte les ventes"], mock_llm=mock, config_overrides=CONFIG_FOCUS)

    assert len(_refus(result)) == 1


def test_sans_prefixe_configure_erreur_n_est_pas_un_echec_d_outil(outils_focus):
    """Les autres agents : « Erreur : » en tête d'une sortie réelle reste une donnée."""
    outils_focus["generate_csv"] = CSV_KO
    mock = MockLLM([f"{METH}\n{CSV}\n{FINAL}", f"{METH}\n{FINAL}"])
    result = bouzecode(["exporte les ventes"], mock_llm=mock)

    refus = _refus(result)
    assert len(refus) == 1
    assert "MÊME lot" in refus[0] and "n'a pas fait son travail" not in refus[0]
