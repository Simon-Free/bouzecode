"""Frottements relevés en pilotant le Bureau avec un vrai modèle (2026-09-24), côté serveur :
un retour envoyé à un agent qui tourne part en file (plus de 409 muet), le coût d'une mission
compte ses sous-agents, un agent tué APRÈS avoir intégré n'est pas un échec, et « Redémarrer »
dit sur quel code il relance.
"""
import json

from bouzecode.web_v2.runtime.runner import agent_fiche, agent_registre, agent_reprise
from bouzecode.web_v2.services.work import micros, tickets
from bouzecode.web_v2.tests.test_v3_gestes_des_taches import (  # noqa: F401 — fixtures
    _faire_tourner, _ticket, client, depot, sans_spawn,
)
from bouzecode.web_v2.tests.test_v3_statut_des_taches import FINAL_ANSWER, ecrire_agent, ligne


# ---------------------------------------------------------- retour pendant que l'agent tourne


def test_un_retour_a_un_agent_qui_tourne_part_en_file_au_lieu_d_un_409(client, depot, sans_spawn):
    micro = micros.create_micro(titre="t", projet_slug=depot)
    premier = client.post(f"/api/micros/{micro['id']}/lancer").get_json()
    _faire_tourner(premier["ticket_id"], "2a2b2c2d2e2f", vivant=True, ipc="running")

    r = client.post(f"/api/micros/{micro['id']}/relancer",
                    json={"retour": "pense aussi au cas vide", "mode": "continuer"})
    assert r.status_code == 200, r.get_data(as_text=True)
    corps = r.get_json()
    assert corps["queued"] is True and corps["agent_id"] == "2a2b2c2d2e2f"
    file = client.get("/api/agents/2a2b2c2d2e2f/queue").get_json()
    textes = [m.get("text") for m in (file.get("queue") or file.get("items") or [])]
    assert "pense aussi au cas vide" in textes
    assert ligne(client, micro["id"])["passages"][0]["retours_envoyes"] == ["pense aussi au cas vide"]
    assert len(sans_spawn) == 1, "aucun nouvel agent"


def test_sans_retour_un_agent_qui_tourne_reste_un_refus_explicite(client, depot, sans_spawn):
    micro = micros.create_micro(titre="t", projet_slug=depot)
    premier = client.post(f"/api/micros/{micro['id']}/lancer").get_json()
    _faire_tourner(premier["ticket_id"], "3a3b3c3d3e3f", vivant=True, ipc="running")
    r = client.post(f"/api/micros/{micro['id']}/relancer", json={"mode": "continuer"})
    assert r.status_code == 409 and r.get_json()["error"]["code"] == "deja_en_cours"


def test_continuer_avec_un_message_le_transmet_a_l_agent(client, depot, sans_spawn, monkeypatch):
    envoye = []
    monkeypatch.setattr(agent_reprise, "continue_agent", lambda agent, texte, **_: envoye.append(texte) or agent)
    micro = micros.create_micro(titre="t", projet_slug=depot)
    premier = client.post(f"/api/micros/{micro['id']}/lancer").get_json()
    _faire_tourner(premier["ticket_id"], "4a4b4c4d4e4f", final=FINAL_ANSWER)
    r = client.post(f"/api/micros/{micro['id']}/relancer",
                    json={"mode": "continuer", "retour": "le test X échoue encore"})
    assert r.status_code == 200 and r.get_json()["mode"] == "continuer"
    assert envoye == ["le test X échoue encore"]


# ---------------------------------------------------------- coût avec les sous-agents


def _log(cout_in):
    return [{"event": "side_call", "model": "claude-sonnet-4-6", "api_input_tokens": cout_in,
             "api_output_tokens": 0, "api_cache_read": 0, "api_cache_create": 0}]


def test_le_cout_d_une_mission_compte_ses_sous_agents(client):
    for agent_id, parent in (("5a0000000001", ""), ("5a0000000002", "5a0000000001"),
                             ("5a0000000003", "5a0000000002")):
        ecrire_agent(agent_id)
        fiche = agent_fiche.AGENTS_DIR / f"{agent_id}.json"
        data = json.loads(fiche.read_text(encoding="utf-8"))
        data["parent"] = parent
        fiche.write_text(json.dumps(data), encoding="utf-8")
        session = agent_fiche.AGENTS_DIR / f"{agent_id}.session.json"
        s = json.loads(session.read_text(encoding="utf-8"))
        s["compaction_log"] = _log(1_000_000)
        session.write_text(json.dumps(s), encoding="utf-8")
    agent_fiche._list_agents_cache.clear()
    agent_registre._agent_file_cache.clear()

    seul = client.get("/api/sessions/agent/5a0000000001/costs").get_json()
    assert "sous_agents" not in seul, "l'agrégat n'est calculé que sur demande"
    tout = client.get("/api/sessions/agent/5a0000000001/costs?avec_sous_agents=1").get_json()
    assert [s["agent_id"] for s in tout["sous_agents"]] == ["5a0000000002", "5a0000000003"]
    propre = tout["total"]["cost"]
    assert propre > 0
    assert tout["total_avec_sous_agents"] == round(propre + sum(s["cost"] for s in tout["sous_agents"]), 4)
    assert tout["total_avec_sous_agents"] == round(3 * propre, 4)


# ---------------------------------------------------------- tué après avoir intégré


def _tue_sans_cloture(agent_id, ticket_id):
    ecrire_agent(agent_id, ticket_id=ticket_id, close_reason="", finished_at="2026-09-23T10:10:00Z")


def _noeud(client, agent_id):
    """Le nœud servi par l'arbre, caches de process vidés (l'arbre est mémorisé par process)."""
    from bouzecode.web_v2.services.sessions import store
    from bouzecode.web_v2.services.work import fleet_cache
    agent_fiche._list_agents_cache.clear()
    store.invalidate_status(agent_id)
    fleet_cache.clear()
    return next(n for n in client.get("/api/agents/tree").get_json()["nodes"]
                if n.get("agent_id") == agent_id)


def test_un_agent_tue_apres_avoir_integre_n_est_pas_un_echec(client, depot, sans_spawn):
    micro = micros.create_micro(titre="t", projet_slug=depot)
    premier = client.post(f"/api/micros/{micro['id']}/lancer").get_json()
    _faire_tourner(premier["ticket_id"], "6a6b6c6d6e6f")
    _tue_sans_cloture("6a6b6c6d6e6f", premier["ticket_id"])

    noeud = _noeud(client, "6a6b6c6d6e6f")
    assert noeud["etat"] == "crashed", "sans intégration, c'est bien un arrêt sans finir"

    #  Lot L2 : intégré = `closed{integre}` (ici semé : l'intégration a eu lieu avant le kill).
    slug, ticket = _ticket(premier["ticket_id"])
    ticket.update(state="closed", state_reason={"code": "integre", "message": "", "at": ""},
                  worktree={"retire_at": "2026-09-23T10:11:00", "branch": "agent/x"})
    tickets._save_unlocked(slug, [ticket])

    noeud = _noeud(client, "6a6b6c6d6e6f")
    assert noeud["etat"] == "finished" and noeud["integre"] is True
    assert noeud["libelle_etat"] == "Terminé — intégré"
    assert ligne(client, micro["id"])["statut_ui"] != "en_echec"


# ---------------------------------------------------------- Redémarrer


def test_la_version_dit_sur_quel_code_redemarrer(client):
    data = client.get("/api/version").get_json()
    assert data["code_root"].endswith("bouzecode")
