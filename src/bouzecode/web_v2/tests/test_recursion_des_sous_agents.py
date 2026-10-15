# [desc] Sous-agents récursifs côté serveur : profondeur passée au spawn (BOUZECODE_AGENT_DEPTH) depuis la chaîne des parents, et réveil en cascade petit-enfant -> enfant -> racine. [/desc]
from __future__ import annotations

import json

from bouzecode.web_v2.runtime.runner import agent_commande, agent_fiche, agent_registre
from bouzecode.web_v2.services.work import profondeur, tickets, wake
from bouzecode.web_v2.tests.test_reveil_d_un_enfant_clos import (  # noqa: F401 — fixtures
    ENFANT, PETIT_ENFANT, RACINE, _clos, _ticket, reveils,
)
from bouzecode.web_v2.tests.test_v3_statut_des_taches import SLUG, ecrire_agent


def _avec_parent(agent_id: str, parent: str) -> None:
    fiche = agent_fiche.AGENTS_DIR / f"{agent_id}.json"
    donnees = json.loads(fiche.read_text(encoding="utf-8"))
    fiche.write_text(json.dumps({**donnees, "parent": parent}), encoding="utf-8")
    agent_fiche._list_agents_cache.clear()
    agent_registre._agent_file_cache.clear()


def test_la_profondeur_suit_la_chaine_des_parents_jusqu_au_spawn():
    ecrire_agent(RACINE)
    _avec_parent(RACINE, "dispatcher:manual")
    ecrire_agent(ENFANT)
    _avec_parent(ENFANT, RACINE)
    ecrire_agent(PETIT_ENFANT)
    _avec_parent(PETIT_ENFANT, ENFANT)

    assert profondeur.chaine_parents(PETIT_ENFANT) == [ENFANT, RACINE]
    env = agent_commande._ticket_env(agent_fiche.load_agent(PETIT_ENFANT))
    assert env["BOUZECODE_AGENT_DEPTH"] == "2"
    assert agent_commande._ticket_env(agent_fiche.load_agent(RACINE))["BOUZECODE_AGENT_DEPTH"] == "0"


def test_un_parent_tui_compte_mais_arrete_la_remontee():
    ecrire_agent(ENFANT)
    _avec_parent(ENFANT, "tui:abc123")
    assert profondeur.chaine_parents(ENFANT) == ["tui:abc123"]
    assert agent_commande._ticket_env(agent_fiche.load_agent(ENFANT))["BOUZECODE_AGENT_DEPTH"] == "1"


def test_le_petit_enfant_reveille_son_parent_qui_reveille_le_sien(reveils):
    """Racine -> enfant (clos en attendant SON enfant) -> petit-enfant. Le petit-enfant livre :
    l'enfant est réveillé (pas la racine, qui travaille). Puis la racine clôt son tour : elle
    est réveillée à son tour avec le compte rendu de l'enfant."""
    ecrire_agent(RACINE, vivant=True, ipc="running")
    enfant = _ticket("refonte du scraper", RACINE, ENFANT)
    petit = _ticket("rapport de mesure", ENFANT, PETIT_ENFANT)
    _clos(PETIT_ENFANT, petit["id"])
    _clos(ENFANT, enfant["id"], cloture_en_attente_des_enfants=True)

    wake.process_wakes()
    assert [agent for agent, _ in reveils] == [ENFANT]
    assert petit["id"] in reveils[0][1]

    _clos(RACINE, "", cloture_en_attente_des_enfants=True)
    wake.process_wakes()

    assert [agent for agent, _ in reveils] == [ENFANT, RACINE]
    assert enfant["id"] in reveils[1][1]
    assert tickets.get_ticket(SLUG, petit["id"])["parent"] == ENFANT
