# [desc] Fins de run et reprises (L2) : close_reasons seule table livré/non livré (C14 : max_turns_exceeded → idle_no_delivery), hook de fin (route interne) et watchdog, reprise à chaud d'un agent livré → running, relance sans drapeau résiduel (C9). [/desc]
from __future__ import annotations

import json
import subprocess
import sys

import psutil
import pytest

from bouzecode.web_v2 import close_reasons
from bouzecode.web_v2.app import create_app
from bouzecode.web_v2.runtime.runner import agent_chaud, agent_fiche, agent_registre
from bouzecode.web_v2.services.sessions import store
from bouzecode.web_v2.services.work import messaging, projects, ticket_fsm, tickets, wake
from bouzecode.web_v2.services.work.fsm import etats
from bouzecode.web_v2.tests.aides_tickets import fiche_agent

SLUG = "p"


@pytest.mark.parametrize(("close_reason", "issue"), [
    ("final_answer", "delivered"), ("ends_turn_tool", "delivered"),
    ("max_turns_exceeded", "idle_no_delivery"), ("empty_completion", "idle_no_delivery"),
    ("final_answer_never_called", "idle_no_delivery"), ("text_no_tools", "idle_no_delivery"),
    ("api_error", "stopped"), ("cancelled", "stopped"), ("", "stopped"),
])
def test_close_reasons_est_la_seule_table_de_fin(close_reason, issue):
    assert close_reasons.issue_de_fin(close_reason)[0] == issue


def test_une_fin_forcee_n_est_jamais_une_livraison_meme_avec_une_reponse():
    assert close_reasons.issue_de_fin("max_turns_exceeded", final_answer=True)[0] == \
        "idle_no_delivery"
    assert close_reasons.issue_de_fin("", final_answer=True)[0] == "delivered"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    chemin = tmp_path / "projects.json"
    monkeypatch.setattr(projects, "PROJECTS_PATH", chemin)
    chemin.write_text(json.dumps([{"slug": SLUG, "name": "p", "path": str(tmp_path)}]),
                      encoding="utf-8")
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def _en_cours(agent_id: str = "a1") -> dict:
    ticket = tickets.create_ticket(SLUG, "T", "faire")
    tickets.set_launching(SLUG, ticket)
    tickets.add_run(SLUG, ticket, agent_id, "work", "m")
    return ticket


def _fin_de_run(client, ticket: dict, close_reason: str):
    """Le hook de fin de l'agent a1 : route interne, avec le jeton de SON run."""
    fiche_agent("a1", slug=SLUG, ticket_id=ticket["id"], run_token="jeton-a1")
    return client.post("/internal/runs/a1/ended", json={"close_reason": close_reason},
                       headers={"X-Bouzecode-Run-Token": "jeton-a1"})


@pytest.mark.parametrize(("close_reason", "state", "code", "livre"), [
    ("max_turns_exceeded", etats.IDLE_NO_DELIVERY, "max_turns_exceeded", False),
    ("final_answer", etats.DELIVERED, "final_answer", True),
    ("api_error", etats.STOPPED, "api_error", False),
    ("cancelled", etats.STOPPED, "interrupted", False),
])
def test_le_hook_de_fin_applique_la_table(client, close_reason, state, code, livre):
    ticket = _en_cours()
    reponse = _fin_de_run(client, ticket, close_reason)
    assert reponse.status_code == 200
    assert reponse.get_json()["state"] == state
    frais = tickets.get_ticket(SLUG, ticket["id"])
    assert frais["state"] == state and frais["state_reason"]["code"] == code
    run = frais["runs"][0]
    assert run["state"] == "ended" and run["end"]["delivered"] is livre
    assert run["end"]["reason"] == close_reason


def test_une_cloture_differee_n_avance_rien(client):
    ticket = _en_cours()
    _fin_de_run(client, ticket, "final_answer_deferred")
    assert tickets.get_ticket(SLUG, ticket["id"])["state"] == etats.RUNNING


def _fiche(agent_id: str, ticket_id: str, cwd: str, **champs) -> agent_fiche.Agent:
    parc = agent_fiche.AGENTS_DIR
    ipc = parc / f"{agent_id}.ipc"
    ipc.mkdir(parents=True, exist_ok=True)
    fiche = {"agent_id": agent_id, "prompt": "Corrige", "model": "m", "cwd": cwd, "pid": None,
             "started_at": "2026-10-01T10:00:00", "returncode": 0, "finished_at": "",
             "session_path": str(parc / f"{agent_id}.session.json"),
             "stdout_path": str(parc / f"{agent_id}.out.log"), "ipc_dir": str(ipc),
             "parent": "", "ticket_slug": SLUG, "ticket_id": ticket_id, **champs}
    (parc / f"{agent_id}.json").write_text(json.dumps(fiche), encoding="utf-8")
    agent_fiche._list_agents_cache.clear()
    agent_registre._agent_file_cache.clear()
    store.invalidate_status(agent_id)
    return agent_fiche.load_agent(agent_id)


def test_le_watchdog_constate_une_fin_forcee_sans_hook(client, tmp_path):
    """Un agent mort dont la session dit `max_turns_exceeded`, sans hook (profil non codeur) :
    deux observations du process mort, puis `idle_no_delivery` — jamais `delivered`."""
    ticket = _en_cours("mort")
    agent = _fiche("mort", ticket["id"], str(tmp_path))
    with open(agent.session_path, "w", encoding="utf-8") as session:
        json.dump({"messages": [], "close_reason": "max_turns_exceeded"}, session)
    wake.tick()
    wake.tick()
    frais = tickets.get_ticket(SLUG, ticket["id"])
    assert frais["state"] == etats.IDLE_NO_DELIVERY
    assert frais["runs"][0]["end"]["delivered"] is False


@pytest.fixture()
def process_chaud(tmp_path):
    """Un VRAI process vivant, dont l'IPC dit `idle` : un agent du warm pool, tour fini."""
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    yield proc
    proc.kill()
    proc.wait(timeout=10)


def test_un_message_a_un_agent_livre_le_repasse_en_cours(client, tmp_path, process_chaud):
    """Reprise à chaud (critère 6) : le ticket ne reste pas « à vérifier » pendant que son agent
    retravaille — la reprise est une transition explicite vers `running`."""
    ticket = _en_cours("chaud")
    ticket_fsm.appliquer(SLUG, ticket["id"], etats.RUN_ENDED, delivered=True)
    agent = _fiche("chaud", ticket["id"], str(tmp_path), pid=process_chaud.pid, returncode=None,
                   pid_create_time=psutil.Process(process_chaud.pid).create_time())
    (agent_fiche.AGENTS_DIR / "chaud.ipc" / "state.json").write_text(
        json.dumps({"status": "idle", "boite": True}), encoding="utf-8")
    store.invalidate_status("chaud")
    assert agent_chaud.is_warm(agent)
    for _ in range(3):  # une lecture ne change rien (B1)
        assert client.get(f"/api/projects/{SLUG}/tickets/{ticket['id']}").get_json()["state"] == \
            etats.DELIVERED
    resultat = messaging.send_to_ticket_agent(SLUG, tickets.get_ticket(SLUG, ticket["id"]),
                                              "Ajoute aussi les tests")
    assert resultat["ok"] and resultat["delivered"]
    frais = tickets.get_ticket(SLUG, ticket["id"])
    assert frais["state"] == etats.RUNNING
    assert [(r["agent_id"], r["state"]) for r in frais["runs"]] == [("chaud", "running")]
    assert [e["kind"] for e in ticket_fsm.events(SLUG, ticket["id"])][-2:] == [
        etats.MESSAGE_SENT, "comment"]


def test_relancer_un_ticket_arrete_ne_garde_aucune_trace_du_cycle_precedent():
    """C9 : un ticket relancé n'est jamais affiché « terminé » ni « planté »."""
    ticket = _en_cours()
    ticket_fsm.appliquer(SLUG, ticket["id"], etats.CRASHED, code="crashed")
    tickets.set_launching(SLUG, ticket)
    assert ticket["state"] == etats.PROVISIONING and ticket["state_reason"] is None
    tickets.add_run(SLUG, ticket, "a2", "work", "m")
    frais = tickets.get_ticket(SLUG, ticket["id"])
    assert (frais["state"], tickets.derive_status(frais)) == (etats.RUNNING, "en cours")
    assert "done" not in frais and "crashed" not in frais
