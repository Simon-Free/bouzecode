# [desc] main attend ses sous-agents lances en fond (CheckAgentResult wait=true en parallele) : quand tous ont fini, l'invite d'attente se referme SEULE et main reprend — sans qu'on touche au clavier, prompt de lancement ou 1er message tape, machine chargee ou non. [/desc]
"""Vrai REPL face au faux LLM HTTP (faux_llm_agents.py, script `[principal:fond]`) : main lance
trois enfants lents en fond, puis les attend par trois CheckAgentResult(wait=true) d'un meme
lot. Les enfants livrent PENDANT que l'invite « [main attend ses sous-agents] » est ouverte.

Machine chargee : sous-agents actifs, la 1re construction de l'invite prend des secondes
(contention du GIL, mesure : 2 s avec 4 fils qui calculent). Avec le prompt de lancement,
cette 1re construction tombe justement pendant une attente de main."""
from __future__ import annotations

import time

import pytest

from bouzecode.backend.multi_agent.en_process.fiche import PRINCIPAL
from bouzecode.ui import paste_input

from .faux_llm_agents import DELAI_ENFANT_LENT, FauxLlmAgents
from .test_tui_sous_agents_e2e import ENTREE, _attendre, _resultats_d_outil, _tui_pilote

DEMANDE = "[principal:fond] lance trois enfants et attends-les"


def _construction_lente(monkeypatch) -> None:
    """La vraie session de saisie, mais construite en 0,6 s (plus que le pas du suivi)."""
    vraie = paste_input.main_session_with

    def lente(*arguments, **options):
        time.sleep(0.6)
        return vraie(*arguments, **options)

    monkeypatch.setattr(paste_input, "main_session_with", lente)


@pytest.mark.parametrize("machine_chargee", [True, False], ids=["machine_chargee", "au_calme"])
@pytest.mark.parametrize("par_le_lancement", [True, False],
                         ids=["prompt_de_lancement", "premier_message_tape"])
def test_main_reprend_seul_quand_ses_sous_agents_ont_fini(monkeypatch, tmp_path, capsys,
                                                          par_le_lancement, machine_chargee):
    """Personne ne tape rien pendant l'attente : des que les trois enfants ont livre, main
    recoit leurs rapports et livre a son tour."""
    monkeypatch.chdir(tmp_path)
    if machine_chargee:
        _construction_lente(monkeypatch)
    lancement = DEMANDE if par_le_lancement else None
    with FauxLlmAgents() as llm, \
            _tui_pilote(monkeypatch, llm, tmp_path, lancement) as (clavier, ecran, config):
        registre = config["_tui_agents"]
        principal = registre.fiche(PRINCIPAL).state
        if not par_le_lancement:
            clavier.send_text(DEMANDE + ENTREE)

        # 1. Les trois enfants tournent, main les attend avec l'invite ouverte.
        _attendre(lambda: len(registre.sous_agents()) == 3, "trois sous-agents")
        enfants = registre.sous_agents()
        _attendre(lambda: all(f.resultat == "rapport lent" and not f.actif for f in enfants),
                  "les trois enfants livrent", DELAI_ENFANT_LENT * 4 + 20,
                  etat=lambda: [(f.description, f.etat) for f in enfants])

        # 2. Sans aucune touche, l'invite d'attente se referme et main livre.
        _attendre(lambda: principal.final_answer == "main a récupéré ses enfants",
                  "main reprend seul apres ses enfants", 5,
                  etat=lambda: [str(m.get("content"))[:80] for m in principal.messages[-3:]])
        rapports = _resultats_d_outil(principal, "CheckAgentResult")
        assert len(rapports) == 3 and all("rapport lent" in r for r in rapports)
        assert len(registre.sous_agents()) == 3, "main n'a relance personne"
        assert "main attend ses sous-agents" in capsys.readouterr().out
