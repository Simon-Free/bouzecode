# [desc] Une clôture que la boucle refuse n'ouvre aucune tâche de suite : seules les suites de la clôture ACCEPTÉE entrent au Bureau. [/desc]
"""Essai DeepSeek du 2026-09-24/25, racine 6bafe9cd (chantier « Portail des énigmes »).

La racine a appelé FinalAnswer 13 fois. Trois de ces clôtures ont passé le validateur puis ont
été refusées par la boucle, parce que FinalAnswer voyageait dans le même lot qu'un Bash dont
elle n'avait pas lu le résultat. Chacune avait déjà ouvert ses suites. Le Bureau montrait donc
« Étendre le scraping » en trois exemplaires, et deux décisions Q25/Q26 identiques.

On joue une vraie conversation (boucle, outils et base réels, seul le modèle est simulé) et on
lit le Bureau à la fin.
"""
from __future__ import annotations

import json

from bouzecode.web_v2.services.work import micros
from tests.e2e_harness import bouzecode
from tests.fake_llm import MockLLM

METH = '<tool_use name="Methodology" id="m1"><param name="content">ok</param></tool_use>'
BASH = '<tool_use name="Bash" id="b1"><param name="command">echo nettoyage</param></tool_use>'


def _cloture(restes: list[str]) -> str:
    declares = json.dumps([{"titre": r} for r in restes], ensure_ascii=False)
    return ('<tool_use name="FinalAnswer" id="f1"><param name="answer">Livré.</param>'
            '<param name="taches_terminees">["scraper Kangourou"]</param>'
            f'<param name="taches_restantes">{declares}</param></tool_use>')


def _suites_au_bureau() -> list[str]:
    return sorted(m["titre"] for m in micros.list_micros() if m["origine"] == "cloture_agent")


def test_une_cloture_refusee_par_la_boucle_n_ouvre_aucune_suite(monkeypatch):
    """1re clôture : jointe à un Bash, refusée. 2e : seule, acceptée, avec un libellé reformulé.
    Le Bureau ne porte que la suite de la clôture acceptée."""
    monkeypatch.setenv("BOUZECODE_RUN_KIND", "work")
    mock = MockLLM([
        f"{METH}\n{BASH}\n{_cloture(['Brancher d autres sites sources que le Kangourou'])}",
        f"{METH}\n{_cloture(['Étendre le scraping à d autres sites'])}",
    ])

    result = bouzecode(["scrape les énigmes"], mock_llm=mock)

    assert result.state.close_reason == "final_answer"
    assert _suites_au_bureau() == ["Étendre le scraping à d autres sites"]


def test_un_budget_de_refus_epuise_ouvre_les_suites_une_seule_fois(monkeypatch):
    """Toutes les clôtures refusées, sauf la dernière forcée par le budget de refus : la
    session se ferme quand même (close_reason garde l'anomalie), et ses suites avec elle —
    une seule fois, pas une fois par tentative."""
    monkeypatch.setenv("BOUZECODE_RUN_KIND", "work")
    mock = MockLLM([f"{METH}\n{BASH}\n{_cloture(['Q25/Q26 sans choix A-E'])}"] * 6)

    result = bouzecode(["scrape les énigmes"], mock_llm=mock)

    assert result.state.close_reason == "close_over_unread_results"
    assert _suites_au_bureau() == ["Q25/Q26 sans choix A-E"]
    assert len(micros.list_micros()) == 1
