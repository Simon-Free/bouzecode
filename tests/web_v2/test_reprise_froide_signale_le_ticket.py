# [desc] Reprise FROIDE (process mort : agent arrêté, question en pause) : comme la reprise chaude, elle ramène le ticket à `running`. Vu en E2E : « Continuer » un agent arrêté le faisait travailler sous un ticket resté `stopped`. Zéro process lancé. [/desc]
from __future__ import annotations

import json

from bouzecode.web_v2.runtime.runner import agent_chaud, agent_fiche, agent_reprise, agent_respawn
from bouzecode.web_v2.services.work import ticket_fsm
from bouzecode.web_v2.services.work import tickets as tickets_svc
from bouzecode.web_v2.services.work.fsm import etats


def _agent_du_ticket(tmp_path, ticket: dict) -> agent_fiche.Agent:
    session = tmp_path / "s.session.json"
    session.write_text(json.dumps({"messages": [{"role": "user", "content": "hi"},
                                                {"role": "assistant", "content": "ok"}]}),
                       encoding="utf-8")
    agent = agent_fiche.Agent(agent_id="a1", prompt="prompt", model="", cwd="", pid=0,
                         started_at="2026-10-06T09:00:00Z", session_path=str(session),
                         stdout_path="", ipc_dir="")
    agent.ticket_slug, agent.ticket_id = "p", ticket["id"]
    return agent


def _ticket_en(etat_vise: str) -> dict:
    """Un vrai ticket du store dont l'agent `a1` a été arrêté (ou a posé une question)."""
    ticket = tickets_svc.create_ticket("p", "t", "prompt")
    tickets_svc.set_launching("p", ticket)
    tickets_svc.add_run("p", ticket, "a1", "work", "")
    if etat_vise == etats.STOPPED:
        ticket_fsm.appliquer("p", ticket["id"], etats.STOP, "utilisateur", agent_id="a1", code="killed")
    return tickets_svc.get_ticket("p", ticket["id"])


def _respawn_sans_process(monkeypatch) -> None:
    """Le respawn réussit sans lancer de process (le vrai lancerait `python -m bouzecode`)."""
    monkeypatch.setattr(agent_respawn, "_respawn", lambda agent, extra_args, banner, model="": agent)
    monkeypatch.setattr(agent_chaud, "_is_warm", lambda agent: False)
    monkeypatch.setattr(agent_chaud, "_joignable_en_tour", lambda agent: False)
    monkeypatch.setattr(agent_chaud, "_adopt_live_session_process", lambda agent: None)


def test_continuer_un_agent_arrete_remet_son_ticket_au_travail(monkeypatch, tmp_path):
    ticket = _ticket_en(etats.STOPPED)
    assert ticket["state"] == etats.STOPPED
    _respawn_sans_process(monkeypatch)

    agent_reprise.continue_agent(_agent_du_ticket(tmp_path, ticket), "Continue là où tu t'es arrêté.")

    assert tickets_svc.get_ticket("p", ticket["id"])["state"] == etats.RUNNING


def test_un_respawn_refuse_ne_touche_pas_au_ticket(monkeypatch, tmp_path):
    ticket = _ticket_en(etats.STOPPED)
    _respawn_sans_process(monkeypatch)
    monkeypatch.setattr(agent_respawn, "_respawn", lambda agent, extra_args, banner, model="": None)

    assert agent_reprise.continue_agent(_agent_du_ticket(tmp_path, ticket), "et après ?") is None
    assert tickets_svc.get_ticket("p", ticket["id"])["state"] == etats.STOPPED
