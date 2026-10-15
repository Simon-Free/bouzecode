# [desc] Lot L6 (reste de L3) : GET /api/agents et GET /api/agents/tree dérivent d'une même collecte (`parc.collecter`) et d'un même relevé (`parc.releve`) : pour chaque agent, même état, même question, même projet, même ticket. [/desc]
from __future__ import annotations

import os

from bouzecode.web_v2.app import create_app
from bouzecode.web_v2.services.work import fleet, parc
from bouzecode.web_v2.tests.aides_tickets import fiche_agent, projet

CHAMPS = ("state", "parent", "question", "options", "project_slug", "ticket_id", "started_at")


def test_la_liste_et_l_arbre_disent_la_meme_chose_de_chaque_agent(tmp_path, monkeypatch):
    projet(tmp_path, monkeypatch, "proj")
    fiche_agent("a0000000000a", slug="proj", ticket_id="t1")
    fiche_agent("b0000000000b", pid=os.getpid(), ipc={"status": "awaiting_input",
                                                      "question": "On part ?",
                                                      "options": ["oui", "non"]})
    fiche_agent("c0000000000c", parent="a0000000000a")
    client = create_app().test_client()
    fleet.clear_tree_cache()

    liste = {r["agent_id"]: r for r in client.get("/api/agents?limit=200").get_json()["agents"]}
    arbre = {n["agent_id"]: n for n in client.get("/api/agents/tree").get_json()["nodes"]
             if n["key"].startswith("agent/")}

    assert set(liste) == set(arbre) == {"a0000000000a", "b0000000000b", "c0000000000c"}
    for agent_id, ligne in liste.items():
        assert {c: ligne[c] for c in CHAMPS} == {c: arbre[agent_id][c] for c in CHAMPS}, agent_id
    assert liste["b0000000000b"]["question"] == "On part ?"
    assert liste["a0000000000a"]["project_slug"] == "proj"


def test_la_collecte_visible_ecarte_les_archives():
    from bouzecode.web_v2.services.sessions import purge
    fiche_agent("d0000000000d")
    fiche_agent("e0000000000e")
    purge.archive_agents(["e0000000000e"])
    assert {a.agent_id for a in parc.collecter()} >= {"d0000000000d", "e0000000000e"}
    assert "e0000000000e" not in {a.agent_id for a in parc.collecter(visibles_seulement=True)}
