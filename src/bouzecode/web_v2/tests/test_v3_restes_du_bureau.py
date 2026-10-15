"""Restes remontés par la refonte du Bureau, joués par HTTP comme le front.

* le prompt d'un agent lancé depuis une tâche commence par le TITRE de la tâche (sans « Tâche : ») ;
* « À traiter » montre le plan à valider et de quoi intégrer une livraison depuis la carte ;
* un message mis en file ne fait plus tomber la liste des agents ;
* deux threads qui sauvent le même agent ne se marchent plus dessus.
"""
import json
import threading

import pytest

from bouzecode.web_v2.app import create_app
from bouzecode.web_v2.runtime.runner import agent_fiche, agent_registre
from bouzecode.web_v2.services.work import _persistence, dispatch, file_messages, micros, projects
from bouzecode.web_v2.tests.test_v3_statut_des_taches import (
    FINAL_ANSWER, SLUG, ecrire_agent, tache_lancee,
)
from bouzecode.web_v2.tests.aides_tickets import constater_tout

PLAN = "# Plan\n\n1. Écrire un test qui échoue\n2. Corriger `src/app.py`\n"


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
    monkeypatch.setattr(dispatch, "_launch_bg", lambda *args, **kw: None)


def _ticket(ticket_id):
    for _slug, ticket in _persistence.all_tickets():
        if ticket.get("id") == ticket_id:
            return ticket
    raise AssertionError(ticket_id)


def _ajouter_plan(agent_id):
    session = agent_fiche.AGENTS_DIR / f"{agent_id}.session.json"
    data = json.loads(session.read_text(encoding="utf-8"))
    data["messages"].append({"role": "assistant", "content": "Voici mon plan.", "tool_calls": [
        {"id": "p1", "name": "WritePlan",
         "input": {"content": PLAN, "user_validation_required": True}}]})
    session.write_text(json.dumps(data), encoding="utf-8")


def _cartes(client):
    constater_tout()  # lot L2 : ce que le watchdog a constaté avant qu'on regarde
    r = client.get("/api/inbox")
    assert r.status_code == 200, r.get_data(as_text=True)
    return r.get_json()["items"]


# ------------------------------------------------------------------ prompt et titre


def test_le_prompt_commence_par_le_titre_de_la_tache(client, depot, sans_spawn):
    macro = micros.create_macro("Auth", projets=[depot])
    micro = micros.create_micro(titre="Corriger le login", corps="Le cookie expire trop tôt.",
                                macro_id=macro["id"])
    r = client.post(f"/api/micros/{micro['id']}/lancer", json={})
    assert r.status_code == 200, r.get_data(as_text=True)
    ticket = _ticket(r.get_json()["ticket_id"])
    premiere_ligne = ticket["prompt"].splitlines()[0]
    assert premiere_ligne == "Corriger le login"
    assert "Tâche :" not in ticket["prompt"]
    assert "Chantier : Auth" in ticket["prompt"]
    assert ticket["title"] == "Corriger le login"


def test_l_apercu_du_prompt_n_a_pas_d_etiquette(client, depot):
    micro = micros.create_micro(titre="Documenter l'API", corps="Toutes les routes publiques.",
                                projet_slug=depot)
    r = client.get(f"/api/micros/{micro['id']}/prompt")
    assert r.status_code == 200
    assert r.get_json()["prompt"].startswith("Documenter l'API\n")


# ------------------------------------------------------------------ « À traiter »


def test_un_plan_a_valider_montre_son_texte_dans_a_traiter(client):
    ecrire_agent("plan00000001", vivant=True, ipc="awaiting_plan_validation",
                 question="Valider le plan ?")
    _ajouter_plan("plan00000001")
    [carte] = [c for c in _cartes(client) if c["agent_id"] == "plan00000001"]
    assert carte["type"] == "plan"
    assert carte["question"]["plan"] == PLAN


def test_un_plan_d_une_tache_montre_aussi_son_texte(client):
    ecrire_agent("plan00000002", vivant=True, ipc="awaiting_plan_validation",
                 question="Valider le plan ?", ticket_id="t-plan")
    _ajouter_plan("plan00000002")
    micro_id, _ = tache_lancee("refacto export", "plan00000002")
    [carte] = [c for c in _cartes(client) if c.get("tache") and c["tache"]["micro_id"] == micro_id]
    assert carte["type"] == "plan" and carte["question"]["plan"] == PLAN


def test_une_livraison_a_relire_porte_de_quoi_l_integrer(client):
    ecrire_agent("livre0000001", final=FINAL_ANSWER)
    micro_id, ticket_id = tache_lancee("corriger le login", "livre0000001")
    [carte] = [c for c in _cartes(client) if c["type"] == "a_relire"
               and c["tache"]["micro_id"] == micro_id]
    assert carte["slug"] == SLUG and carte["ticket_id"] == ticket_id
    assert isinstance(carte["integrable"], bool)


# ------------------------------------------------------------------ file de messages


def test_un_message_en_file_ne_casse_ni_la_liste_ni_le_bureau(client):
    ecrire_agent("occupe000001", vivant=True, ipc="running")
    r = client.post("/api/agents/occupe000001/messages",
                    json={"text": "pense aussi aux tests", "mode": "queue"})
    assert r.status_code == 202, r.get_data(as_text=True)
    assert not list(agent_fiche.AGENTS_DIR.glob("*.queue.json")), "plus rien à la racine du parc"
    agent_fiche._list_agents_cache.clear()
    assert "occupe000001" in {a.agent_id for a in agent_registre.list_agents()}
    assert client.get("/api/lignes").status_code == 200
    assert [m["text"] for m in file_messages.lister("occupe000001")] == ["pense aussi aux tests"]


def test_une_file_de_l_ancien_emplacement_est_reprise(client):
    ancien = agent_fiche.AGENTS_DIR / "ancien000001.queue.json"
    ancien.write_text(json.dumps([{"id": "q1", "text": "message d'avant"}]), encoding="utf-8")
    assert [m["text"] for m in file_messages.lister("ancien000001")] == ["message d'avant"]
    assert not ancien.exists()
    assert client.get("/api/lignes").status_code == 200


# ------------------------------------------------------------------ sauvegarde concurrente


def test_deux_threads_qui_sauvent_le_meme_agent_ne_se_genent_pas():
    ecrire_agent("concurrent01")
    agent = agent_fiche.load_agent("concurrent01")
    depart = threading.Barrier(8)
    erreurs: list[BaseException] = []

    def sauver():
        depart.wait()
        try:
            for _ in range(25):
                agent_fiche._save(agent)
        except BaseException as erreur:  # noqa: BLE001 — on veut voir TOUTE erreur
            erreurs.append(erreur)

    fils = [threading.Thread(target=sauver) for _ in range(8)]
    for fil in fils:
        fil.start()
    for fil in fils:
        fil.join()
    assert erreurs == []
    assert json.loads((agent_fiche.AGENTS_DIR / "concurrent01.json").read_text(encoding="utf-8"))[
        "agent_id"] == "concurrent01"
    assert not list(agent_fiche.AGENTS_DIR.glob("concurrent01*.tmp")), "aucun temporaire abandonné"
