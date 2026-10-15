"""SPEC v3 §4.7 — lancer, relancer avec un retour, arrêter, rouvrir : les gestes d'une tâche,
joués par HTTP comme le front. Aucun agent réel ne démarre : `_launch_bg` est remplacé par un
compteur (même technique que test_micro_relance_apres_agent_mort), et le kill est inerte sous
pytest (`runner.destruction_permitted`).
"""
import json

import pytest

from bouzecode.web_v2.app import create_app
from bouzecode.web_v2.services.work import _persistence, dispatch, micros, projects, tickets
from bouzecode.web_v2.tests.aides_tickets import constater_tout
from bouzecode.web_v2.tests.test_v3_statut_des_taches import (
    FINAL_ANSWER, SLUG, ecrire_agent, ligne,
)


@pytest.fixture()
def client():
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


@pytest.fixture()
def depot(tmp_path):
    chemin = tmp_path / "demo"
    chemin.mkdir()
    projects.PROJECTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    projects.PROJECTS_PATH.write_text(json.dumps(
        [{"slug": SLUG, "name": "demo", "path": str(chemin)}]), encoding="utf-8")
    return SLUG


@pytest.fixture()
def sans_spawn(monkeypatch):
    lances: list[tuple] = []
    monkeypatch.setattr(dispatch, "_launch_bg", lambda *args, **kw: lances.append(args))
    return lances


def _ticket(ticket_id):
    for slug, ticket in _persistence.all_tickets():
        if ticket.get("id") == ticket_id:
            return slug, ticket
    raise AssertionError(ticket_id)


def _faire_tourner(ticket_id, agent_id, **agent):
    """Le lancement différé a abouti : le ticket porte un run de travail vers `agent_id`, et
    le watchdog a constaté ce que fait l'agent (fini, question, au travail)."""
    slug, ticket = _ticket(ticket_id)
    tickets.add_run(slug, ticket, agent_id, "work", "m")
    ecrire_agent(agent_id, ticket_id=ticket_id, **agent)
    constater_tout()


# ------------------------------------------------------------------------------ lancer


def test_lancer_sans_depot_est_refuse_et_la_tache_reste_brouillon(client, sans_spawn):
    micro = micros.create_micro(titre="sans dépôt")
    r = client.post(f"/api/micros/{micro['id']}/lancer", json={})
    assert r.status_code == 400 and r.get_json()["error"]["code"] == "depot_requis"
    assert micros.get_micro(micro["id"])["etat"] == "brouillon"
    assert not sans_spawn


def test_lancer_prend_le_depot_du_chantier_et_titre_le_ticket(client, depot, sans_spawn):
    macro = micros.create_macro("Auth", projets=[depot])
    micro = micros.create_micro(titre="Corriger le login", corps="détails\nsuite",
                                macro_id=macro["id"])
    r = client.post(f"/api/micros/{micro['id']}/lancer", json={})
    assert r.status_code == 200, r.get_data(as_text=True)
    corps = r.get_json()
    assert corps["projet_slug"] == depot
    assert corps["launch_key"] == f"launching/{corps['ticket_id']}"
    assert micros.get_micro(micro["id"])["etat"] == "lancee"
    _, ticket = _ticket(corps["ticket_id"])
    assert ticket["title"] == "Corriger le login", "le ticket porte le titre de la tâche"
    assert len(sans_spawn) == 1
    l = ligne(client, micro["id"])
    assert l["statut_ui"] == "en_cours" and l["passages"][0]["etat"] == "preparing"


def test_lancer_deux_fois_est_refuse_tant_que_ca_tourne(client, depot, sans_spawn):
    micro = micros.create_micro(titre="un seul agent", projet_slug=depot)
    assert client.post(f"/api/micros/{micro['id']}/lancer").status_code == 200
    second = client.post(f"/api/micros/{micro['id']}/lancer")
    assert second.status_code == 409 and second.get_json()["error"]["code"] == "deja_en_cours"
    assert len(sans_spawn) == 1


def test_env_api_ko_refuse_le_lancement_en_le_disant(client, depot, sans_spawn, monkeypatch):
    from bouzecode.web_v2 import api_sanity
    monkeypatch.setattr(api_sanity, "BOOT_API_OK", False)
    monkeypatch.setattr(api_sanity, "_maybe_recheck", lambda: None)
    micro = micros.create_micro(titre="t", projet_slug=depot)
    r = client.post(f"/api/micros/{micro['id']}/lancer")
    assert r.status_code == 503 and r.get_json()["error"]["code"] == "env_indisponible"
    assert micros.get_micro(micro["id"])["etat"] == "brouillon"


# ---------------------------------------------------------------------------- relancer


def test_le_prompt_du_passage_suivant_contient_l_historique_et_les_retours(
        client, depot, sans_spawn):
    micro = micros.create_micro(titre="Corriger le login", projet_slug=depot)
    premier = client.post(f"/api/micros/{micro['id']}/lancer").get_json()
    _faire_tourner(premier["ticket_id"], "f1f2f3f4f5f6", final=FINAL_ANSWER)

    apercu = client.get(f"/api/micros/{micro['id']}/prompt",
                        query_string={"retour": "le SSO doit passer par Keycloak"}).get_json()
    assert apercu["passages_inclus"] == 1 and apercu["retours_inclus"] == 1
    for attendu in ("Corriger le login", "corriger le login", "brancher le SSO",
                    "garder l'ancien cookie ?", "le SSO doit passer par Keycloak"):
        assert attendu in apercu["prompt"], attendu

    r = client.post(f"/api/micros/{micro['id']}/relancer",
                    json={"retour": "le SSO doit passer par Keycloak", "mode": "nouvel_agent"})
    assert r.status_code == 200, r.get_data(as_text=True)
    second = r.get_json()
    assert second["mode"] == "nouvel_agent" and second["ticket_id"] != premier["ticket_id"]
    _, ticket = _ticket(second["ticket_id"])
    assert "brancher le SSO" in ticket["prompt"], "le nouvel agent reçoit le récap précédent"
    assert "Keycloak" in ticket["prompt"]
    l = ligne(client, micro["id"])
    assert [p["numero"] for p in l["passages"]] == [2, 1]
    assert l["passages"][0]["retour"] == "le SSO doit passer par Keycloak"
    assert [r["texte"] for r in l["retours"]] == ["le SSO doit passer par Keycloak"]


def test_relancer_par_defaut_continue_avec_l_agent_joignable(client, depot, sans_spawn,
                                                              monkeypatch):
    from bouzecode.web_v2.runtime.runner import agent_reprise
    envoye = []
    monkeypatch.setattr(agent_reprise, "continue_agent", lambda agent, texte, **_: envoye.append(texte) or agent)
    micro = micros.create_micro(titre="t", projet_slug=depot)
    premier = client.post(f"/api/micros/{micro['id']}/lancer").get_json()
    _faire_tourner(premier["ticket_id"], "0a0b0c0d0e0f", final=FINAL_ANSWER)
    assert ligne(client, micro["id"])["joignable"] is True

    r = client.post(f"/api/micros/{micro['id']}/relancer", json={"retour": "ajoute un test"})
    assert r.status_code == 200, r.get_data(as_text=True)
    assert r.get_json()["mode"] == "continuer"
    assert envoye == ["ajoute un test"]
    assert len(sans_spawn) == 1, "continuer ne lance aucun nouvel agent"
    l = ligne(client, micro["id"])
    assert l["passages"][0]["retours_envoyes"] == ["ajoute un test"]


def test_continuer_un_agent_introuvable_est_refuse(client, depot, sans_spawn):
    micro = micros.create_micro(titre="t", projet_slug=depot)
    premier = client.post(f"/api/micros/{micro['id']}/lancer").get_json()
    slug, ticket = _ticket(premier["ticket_id"])
    tickets.add_run(slug, ticket, "fantome00000", "work", "m")   # aucune fiche sur disque
    constater_tout()  # le watchdog constate la fiche introuvable : `stopped{introuvable}`
    r = client.post(f"/api/micros/{micro['id']}/relancer", json={"mode": "continuer"})
    assert r.status_code == 409 and r.get_json()["error"]["code"] == "non_joignable"


# ------------------------------------------------------------------ arrêter / états


def test_rouvrir_pendant_que_l_agent_tourne_est_refuse_mais_abandonner_l_arrete(
        client, depot, sans_spawn):
    micro = micros.create_micro(titre="t", projet_slug=depot)
    premier = client.post(f"/api/micros/{micro['id']}/lancer").get_json()
    _faire_tourner(premier["ticket_id"], "1a1b1c1d1e1f", vivant=True, ipc="running")

    rouvrir = client.post(f"/api/micros/{micro['id']}/etat", json={"etat": "brouillon"})
    assert rouvrir.status_code == 409 and rouvrir.get_json()["error"]["code"] == "agent_actif"

    abandon = client.post(f"/api/micros/{micro['id']}/etat", json={"etat": "abandonnee"})
    assert abandon.status_code == 200, abandon.get_data(as_text=True)
    assert abandon.get_json()["arretes"] == ["1a1b1c1d1e1f"]
    assert micros.get_micro(micro["id"])["etat"] == "abandonnee"


def test_arreter_sans_agent_actif_le_dit(client):
    micro = micros.create_micro(titre="t")
    r = client.post(f"/api/micros/{micro['id']}/arreter")
    assert r.status_code == 409 and r.get_json()["error"]["code"] == "rien_a_arreter"


def test_rouvrir_une_tache_faite_ou_abandonnee(client):
    for etat in ("faite", "abandonnee"):
        micro = micros.create_micro(titre=f"t {etat}")
        assert client.post(f"/api/micros/{micro['id']}/etat", json={"etat": etat}).status_code == 200
        r = client.post(f"/api/micros/{micro['id']}/etat", json={"etat": "brouillon"})
        assert r.status_code == 200, r.get_data(as_text=True)
        assert r.get_json()["micro"]["etat"] == "brouillon"


def test_la_raison_d_un_changement_d_etat_n_est_ajoutee_qu_une_fois(client):
    micro = micros.create_micro(titre="t")
    client.post(f"/api/micros/{micro['id']}/etat", json={"etat": "faite", "pourquoi": "doublon"})
    precisions = [p["texte"] for p in micros.get_micro(micro["id"])["precisions"]]
    assert precisions == ["doublon"]


def test_integrer_un_passage_inconnu_est_un_404(client):
    micro = micros.create_micro(titre="t")
    r = client.post(f"/api/micros/{micro['id']}/passages/nexistepas/integrer")
    assert r.status_code == 404 and r.get_json()["error"]["code"] == "passage_inconnu"


# ------------------------------------------------------------------------ à traiter


def test_a_traiter_rassemble_questions_livraisons_echecs_et_decisions(client, depot, sans_spawn):
    micros.create_micro(titre="trancher le format", decision=True)
    livree = micros.create_micro(titre="livrée", projet_slug=depot)
    t1 = client.post(f"/api/micros/{livree['id']}/lancer").get_json()["ticket_id"]
    _faire_tourner(t1, "2a2b2c2d2e2f", final=FINAL_ANSWER)
    question = micros.create_micro(titre="questionne", projet_slug=depot)
    t2 = client.post(f"/api/micros/{question['id']}/lancer").get_json()["ticket_id"]
    _faire_tourner(t2, "3a3b3c3d3e3f", vivant=True, ipc="awaiting_input", question="ISO ?")
    ecrire_agent("4a4b4c4d4e4f", vivant=True, ipc="awaiting_input", question="hors tâche ?")

    inbox = client.get("/api/inbox").get_json()
    types = [(c["type"], c["titre"]) for c in inbox["items"]]
    assert inbox["compte"] == 4, types
    assert types[0][0] == "question" and types[1][0] == "question", "les questions d'abord"
    assert ("a_relire", "livrée") in types and ("decision", "trancher le format") in types
    carte = next(c for c in inbox["items"] if c["agent_id"] == "3a3b3c3d3e3f")
    assert carte["question"]["texte"] == "ISO ?" and carte["tache"]["micro_id"] == question["id"]
    assert "repondre" in carte["actions"]
    relire = next(c for c in inbox["items"] if c["type"] == "a_relire")
    assert relire["recap"]["reste"] == ["brancher le SSO"]
    assert client.get("/api/nav/counts").get_json()["a_moi"] == 4


# ------------------------------------------------------------------------ file d'attente


def test_un_message_pendant_le_tour_attend_puis_part(client, monkeypatch):
    from bouzecode.web_v2.runtime.runner import agent_reprise
    from bouzecode.web_v2.services.work import file_messages
    ecrire_agent("5a5b5c5d5e5f", vivant=True, ipc="running")
    r = client.post("/api/agents/5a5b5c5d5e5f/messages", json={"text": "et les tests ?",
                                                               "mode": "queue"})
    assert r.status_code == 202, r.get_data(as_text=True)
    assert [i["text"] for i in client.get("/api/agents/5a5b5c5d5e5f/queue").get_json()["items"]] \
        == ["et les tests ?"]
    assert file_messages.livrer_si_pret("5a5b5c5d5e5f") is None, "le tour n'est pas fini"

    envoye = []
    monkeypatch.setattr(agent_reprise, "continue_agent", lambda agent, texte, **_: envoye.append(texte) or agent)
    ecrire_agent("5a5b5c5d5e5f", ipc="finished", final=FINAL_ANSWER)   # le tour s'est terminé
    from bouzecode.web_v2.services.sessions import store
    store.invalidate_status("5a5b5c5d5e5f")
    assert file_messages.livrer_si_pret("5a5b5c5d5e5f") == {"ok": True}
    assert envoye == ["et les tests ?"]
    assert client.get("/api/agents/5a5b5c5d5e5f/queue").get_json()["items"] == []


def test_annuler_un_message_en_file(client):
    ecrire_agent("6a6b6c6d6e6f", vivant=True, ipc="running")
    qid = client.post("/api/agents/6a6b6c6d6e6f/messages",
                      json={"text": "x", "mode": "queue"}).get_json()["queue_id"]
    assert client.delete(f"/api/agents/6a6b6c6d6e6f/queue/{qid}").status_code == 200
    assert client.delete(f"/api/agents/6a6b6c6d6e6f/queue/{qid}").status_code == 404


# ----------------------------------------------------------------------------- arbre


def test_l_arbre_parle_le_lexique_et_montre_la_tache_liee(client, depot, sans_spawn):
    from bouzecode.web_v2.services.work import fleet
    micro = micros.create_micro(titre="Corriger le login", projet_slug=depot)
    ticket_id = client.post(f"/api/micros/{micro['id']}/lancer").get_json()["ticket_id"]
    _faire_tourner(ticket_id, "7a7b7c7d7e7f", final=FINAL_ANSWER)
    fleet.clear_tree_cache()
    noeuds = client.get("/api/agents/tree").get_json()["nodes"]
    noeud = next(n for n in noeuds if n["agent_id"] == "7a7b7c7d7e7f")
    assert noeud["etat"] == "finished" and noeud["libelle_etat"] == "Terminé"
    assert noeud["micro_id"] == micro["id"] and noeud["tache_titre"] == "Corriger le login"


def test_un_lancement_echoue_apparait_dans_l_arbre(client, depot):
    ticket = tickets.create_ticket(depot, "cassé", "cassé")
    tickets.set_launching(depot, ticket)
    dispatch.record_launch_failure(depot, ticket, "uv sync a échoué")
    from bouzecode.web_v2.services.work import fleet
    fleet.clear_tree_cache()
    noeuds = client.get("/api/agents/tree").get_json()["nodes"]
    echec = next(n for n in noeuds if n["key"] == f"failed/{ticket['id']}")
    assert echec["etat"] == "launch_failed" and "uv sync" in echec["launch_error"]


def test_restaurer_rien_est_un_404(client):
    r = client.post("/api/sessions/agent/inconnu000000/restore")
    assert r.status_code == 404 and r.get_json()["error"]["code"] == "inconnu"


# ------------------------------------------------------------------ création de ticket


def test_une_creation_differee_donne_la_cle_d_onglet(client, depot, sans_spawn):
    r = client.post(f"/api/projects/{depot}/tickets", json={"title": "fais ça", "prompt": "fais ça",
                                                           "defer": True})
    assert r.status_code == 201, r.get_data(as_text=True)
    corps = r.get_json()
    assert corps["launch_key"] == f"launching/{corps['ticket_id']}"
    assert corps["isolation"] == "shared"  # projet hors git : seul `shared` est possible
