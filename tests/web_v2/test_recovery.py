"""Récupération manuelle des conversations interrompues (crash/restart).

Prouve via app.test_client() (aucun mock, fakes purs + injection de dépendance) :
  (i)   un run crashé sans callback est « interrompu » et PAS auto-reworké ;
  (ii)  GET /api/agents?state=interrupted liste ces interrompus (et exclut fin propre) ;
  (iii) POST /api/agents/<id>/messages relance l'agent de sa session ; 404 si inconnu ;
  (iv)  une fin propre (final_answer + verdict disque) est auto-réconciliée sans callback
        et EXCLUE des interrompus.
"""
from __future__ import annotations

import json

import pytest

from bouzecode.web_v2.runtime.runner.agent_fiche import Agent
from bouzecode.web_v2.runtime.runner import agent_fiche, agent_reprise


def _write_session(path, *, close_reason=None, verdict_line=None):
    messages = []
    if verdict_line:
        messages.append({"role": "assistant", "content": verdict_line})
    data = {"messages": messages}
    if close_reason is not None:
        data["close_reason"] = close_reason
    path.write_text(json.dumps(data), encoding="utf-8")


def _make_agent(tmp_path, agent_id, *, close_reason=None, verdict_line=None):
    session_path = tmp_path / f"{agent_id}.session.json"
    ipc_dir = tmp_path / f"{agent_id}.ipc"
    ipc_dir.mkdir(parents=True, exist_ok=True)
    _write_session(session_path, close_reason=close_reason, verdict_line=verdict_line)
    return Agent(
        agent_id=agent_id,
        prompt=f"tâche {agent_id}",
        model="test-model",
        cwd=str(tmp_path),
        pid=999999,
        started_at="2026-07-01T10:00:00Z",
        stdout_path=str(tmp_path / f"{agent_id}.out.log"),
        session_path=str(session_path),
        ipc_dir=str(ipc_dir),
        returncode=0,  # process mort → finished déterministe (pas de subprocess)
    )


@pytest.fixture()
def agents(tmp_path):
    # crashé : pas de close_reason final_answer → interrompu
    crashed = _make_agent(tmp_path, "crashaaaa0001")
    # fin propre : close_reason final_answer + verdict OK sur disque
    clean = _make_agent(
        tmp_path, "cleanbbbb0002",
        close_reason="final_answer",
        verdict_line="VERDICT: OK",
    )
    return {"crashed": crashed, "clean": clean}


@pytest.fixture()
def client(tmp_path, agents, monkeypatch):
    from bouzecode.web_v2.services.sessions import store
    from bouzecode.web_v2.runtime.runner import agent_registre

    monkeypatch.setattr(store, "DAILY_DIR", tmp_path / "no_daily")
    monkeypatch.setattr(store, "CACHE_PATH", tmp_path / "cache.json")
    monkeypatch.setattr(agent_registre, "list_agents",
                        lambda: [agents["crashed"], agents["clean"]])

    from bouzecode.web_v2.app import create_app
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


# (i) run crashé sans callback = interrompu, PAS auto-reworké
def test_crashed_run_is_interrupted_not_reworked(client, agents):
    from bouzecode.web_v2.services.sessions import recovery, store

    sessions = store.list_sessions()["agents"]
    crashed_item = next(a for a in sessions if a["key"] == "agent/crashaaaa0001")
    assert crashed_item["status"]["state"] == "finished"
    assert crashed_item["close_reason"] != "final_answer"
    assert recovery.is_interrupted(crashed_item) is True
    # il ne porte aucun verdict → jamais auto-validé/reworké
    assert "verdict" not in crashed_item


# (ii) GET liste les interrompus, exclut la fin propre
def test_get_interrupted_lists_only_crashed(client):
    resp = client.get("/api/agents?state=interrupted")
    assert resp.status_code == 200
    body = resp.get_json()
    keys = [c["key"] for c in body["agents"]]
    assert "agent/crashaaaa0001" in keys
    assert "agent/cleanbbbb0002" not in keys
    item = next(c for c in body["agents"] if c["key"] == "agent/crashaaaa0001")
    assert item["agent_id"] == "crashaaaa0001"


# (iii) POST /api/agents/<id>/messages → l'agent repart de sa session ; 404 si inconnu
def test_relancer_reprend_l_agent_par_la_remise_unique(client, agents, monkeypatch):
    old = agents["crashed"]
    monkeypatch.setattr(agent_fiche, "load_agent",
                        lambda aid: old if aid == old.agent_id else None)

    # la relance doit re-homer AVANT de resumer, sinon un worktree fauché
    # ressuscite l'agent dans un dossier vide. On trace l'ordre des appels.
    from bouzecode.web_v2.services.work import dispatch
    order = []
    monkeypatch.setattr(dispatch, "rehome_agent_cwd",
                        lambda a: order.append("rehome"))

    def _fake_continue(agent, prompt, model="", **_options):
        order.append(("resume", prompt))
        return agent
    monkeypatch.setattr(agent_reprise, "continue_agent", _fake_continue)

    resp = client.post("/api/agents/crashaaaa0001/messages",
                       json={"text": "Reprends la tâche."})
    assert resp.status_code == 200
    assert resp.get_json() == {"ok": True, "delivered": True, "queued": False}
    # re-home STRICTEMENT avant la reprise
    assert order == ["rehome", ("resume", "Reprends la tâche.")]


def test_relancer_un_inconnu_rend_404(client, monkeypatch):
    monkeypatch.setattr(agent_fiche, "load_agent", lambda aid: None)
    resp = client.post("/api/agents/inexistant/messages", json={"text": "reprends"})
    assert resp.status_code == 404
    assert "error" in resp.get_json()


# (iv) fin propre exclue des interrompus
def test_clean_finish_excluded_from_interrupted(client, agents):
    from bouzecode.web_v2.services.sessions import recovery, store

    # exclue des interrompus
    resp = client.get("/api/agents?state=interrupted")
    keys = [c["key"] for c in resp.get_json()["agents"]]
    assert "agent/cleanbbbb0002" not in keys

    clean_item = next(a for a in store.list_sessions()["agents"]
                      if a["key"] == "agent/cleanbbbb0002")
    assert clean_item["close_reason"] == "final_answer"
    assert recovery.is_interrupted(clean_item) is False

