# [desc] POST …/runs sur un ticket dont l'agent est MORT (clôture écrite dans sa session) mais pas encore constaté par le watchdog : la relance constate la fin d'abord au lieu de répondre 409 `deja_actif`. Vu en E2E (Relancer proposé par la liste, refusé ~15 s). Un process vivant n'est jamais conclu. [/desc]
from __future__ import annotations

import json

from bouzecode.web_v2.runtime.runner import agent_fiche, agent_vivacite
from bouzecode.web_v2.services.work import tickets as tickets_svc
from bouzecode.web_v2.services.work.api_tickets import lancement
from bouzecode.web_v2.services.work.fsm import etats


def _ticket_en_cours(tmp_path, close_reason: str) -> tuple[dict, agent_fiche.Agent]:
    """Un vrai ticket `running` dont le run est l'agent `a1`, session écrite sur disque."""
    ticket = tickets_svc.create_ticket("p", "t", "prompt")
    tickets_svc.set_launching("p", ticket)
    tickets_svc.add_run("p", ticket, "a1", "work", "")
    session = tmp_path / "a1.session.json"
    session.write_text(json.dumps({"messages": [], "close_reason": close_reason}), encoding="utf-8")
    agent = agent_fiche.Agent(agent_id="a1", prompt="prompt", model="", cwd="", pid=0,
                         started_at="2026-10-06T09:00:00Z", session_path=str(session),
                         stdout_path="", ipc_dir="")
    return tickets_svc.get_ticket("p", ticket["id"]), agent


def _parc(monkeypatch, agent: agent_fiche.Agent, vivant: bool) -> None:
    monkeypatch.setattr(agent_fiche, "load_agent", lambda agent_id: agent if agent_id == "a1" else None)
    monkeypatch.setattr(agent_vivacite, "is_running", lambda a: vivant)


def test_un_agent_plante_non_constate_est_constate_avant_la_relance(monkeypatch, tmp_path):
    ticket, agent = _ticket_en_cours(tmp_path, "api_error")
    assert ticket["state"] == etats.RUNNING
    _parc(monkeypatch, agent, vivant=False)

    frais = lancement._constater_une_fin_deja_ecrite("p", ticket)

    assert frais["state"] == etats.STOPPED
    assert frais["state"] not in etats.ACTIFS, "set_launching doit maintenant accepter la relance"


def test_un_agent_vivant_n_est_jamais_conclu(monkeypatch, tmp_path):
    ticket, agent = _ticket_en_cours(tmp_path, "api_error")
    _parc(monkeypatch, agent, vivant=True)

    assert lancement._constater_une_fin_deja_ecrite("p", ticket)["state"] == etats.RUNNING


def test_un_process_parti_sans_cloture_lisible_reste_au_watchdog(monkeypatch, tmp_path):
    ticket, agent = _ticket_en_cours(tmp_path, "")
    _parc(monkeypatch, agent, vivant=False)

    assert lancement._constater_une_fin_deja_ecrite("p", ticket)["state"] == etats.RUNNING
