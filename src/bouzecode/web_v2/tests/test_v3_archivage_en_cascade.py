"""SPEC v3 §4.6 — classer une tâche (faite / abandonnée) archive ses tickets et les
conversations de leurs agents, sous-agents compris ; la rouvrir les ramène, sans toucher à ce
que l'utilisateur avait archivé à la main. Tout est observé par HTTP, comme le front."""
import json

import pytest

from bouzecode.web_v2.runtime.runner import agent_fiche, agent_registre
from bouzecode.web_v2.services.work import micros, tickets
from bouzecode.web_v2.tests.test_v3_gestes_des_taches import (  # noqa: F401 (fixtures)
    _faire_tourner, client, depot, sans_spawn,
)
from bouzecode.web_v2.tests.test_v3_statut_des_taches import FINAL_ANSWER, ecrire_agent


def _ids(client, **params):
    noeuds = client.get("/api/agents/tree", query_string=params).get_json()["nodes"]
    return {n.get("agent_id") for n in noeuds}


def _sous_agent(agent_id, parent):
    ecrire_agent(agent_id, final=FINAL_ANSWER)
    fiche = agent_fiche.AGENTS_DIR / f"{agent_id}.json"
    donnees = json.loads(fiche.read_text(encoding="utf-8"))
    donnees["parent"] = parent
    fiche.write_text(json.dumps(donnees), encoding="utf-8")
    agent_fiche._list_agents_cache.clear()
    agent_registre._agent_file_cache.clear()


def _tache_terminee(client, depot, agent_id="a1a2a3a4a5a6"):
    micro = micros.create_micro(titre="Corriger le login", projet_slug=depot)
    lance = client.post(f"/api/micros/{micro['id']}/lancer").get_json()
    _faire_tourner(lance["ticket_id"], agent_id, final=FINAL_ANSWER)
    return micro, lance["ticket_id"]


def _etat(client, micro, etat):
    r = client.post(f"/api/micros/{micro['id']}/etat", json={"etat": etat})
    assert r.status_code == 200, r.get_data(as_text=True)
    return r.get_json()


@pytest.fixture(autouse=True)
def _arbre_frais(monkeypatch):
    from bouzecode.web_v2.services.work import fleet
    fleet.clear_tree_cache()
    yield
    fleet.clear_tree_cache()


def test_classer_faite_archive_tickets_et_conversations_sous_agents_compris(
        client, depot, sans_spawn):
    micro, ticket_id = _tache_terminee(client, depot)
    _sous_agent("b1b2b3b4b5b6", parent="a1a2a3a4a5a6")
    assert {"a1a2a3a4a5a6", "b1b2b3b4b5b6"} <= _ids(client)

    corps = _etat(client, micro, "faite")

    assert corps["archives"] == {"tickets": 1, "conversations": 2}
    assert not {"a1a2a3a4a5a6", "b1b2b3b4b5b6"} & _ids(client)
    assert {"a1a2a3a4a5a6", "b1b2b3b4b5b6"} <= _ids(client, archived=1)
    assert tickets.get_ticket(depot, ticket_id)["archived"] is True


def test_rouvrir_restaure_ce_que_la_tache_avait_archive(client, depot, sans_spawn):
    micro, ticket_id = _tache_terminee(client, depot)
    _etat(client, micro, "faite")

    corps = _etat(client, micro, "brouillon")

    assert corps["restaures"] == {"tickets": 1, "conversations": 1}
    assert "a1a2a3a4a5a6" in _ids(client)
    assert not tickets.get_ticket(depot, ticket_id).get("archived")


def test_une_conversation_archivee_a_la_main_reste_archivee_a_la_reouverture(
        client, depot, sans_spawn):
    micro, _ = _tache_terminee(client, depot)
    client.post("/api/conversations/archive", json={"keys": ["agent/a1a2a3a4a5a6"]})

    assert _etat(client, micro, "faite")["archives"]["conversations"] == 0
    assert _etat(client, micro, "brouillon")["restaures"]["conversations"] == 0
    assert "a1a2a3a4a5a6" not in _ids(client)


def test_classer_puis_rouvrir_deux_fois_ne_duplique_rien(client, depot, sans_spawn):
    micro, _ = _tache_terminee(client, depot)
    _etat(client, micro, "faite")
    _etat(client, micro, "brouillon")
    assert _etat(client, micro, "faite")["archives"] == {"tickets": 1, "conversations": 1}
    assert _etat(client, micro, "brouillon")["restaures"] == {"tickets": 1, "conversations": 1}
    assert "a1a2a3a4a5a6" in _ids(client)


def test_abandonner_une_tache_en_cours_arrete_puis_archive_l_agent(client, depot, sans_spawn):
    micro = micros.create_micro(titre="en cours", projet_slug=depot)
    lance = client.post(f"/api/micros/{micro['id']}/lancer").get_json()
    _faire_tourner(lance["ticket_id"], "c1c2c3c4c5c6", vivant=True, ipc="running")

    corps = _etat(client, micro, "abandonnee")

    assert corps["arretes"] == ["c1c2c3c4c5c6"]
    assert corps["archives"] == {"tickets": 1, "conversations": 1}
    #  Sous pytest le kill est inerte (le « process » est le test lui-même) : l'agent reste
    #  vivant, donc visible — règle voulue (`visibility.hidden_by_archive`). Ce qui prouve
    #  l'archivage, c'est son inscription au registre avec la provenance de la tâche.
    from bouzecode.web_v2.services.sessions import purge
    assert purge.load_deleted()["agent/c1c2c3c4c5c6"]["reason"] == f"tache:{micro['id']}"


def test_un_ticket_introuvable_n_empeche_pas_le_reste(client, depot, sans_spawn):
    micro, _ = _tache_terminee(client, depot)
    micros.lier_ticket(micro["id"], depot, "ticket-fantome")
    corps = _etat(client, micro, "faite")
    assert corps["archives"]["tickets"] == 1
    assert corps["archives"]["erreurs"] == [{"ticket_id": "ticket-fantome",
                                             "error": "ticket introuvable"}]
