"""Récupération manuelle des conversations interrompues (crash/restart).

Prouve via app.test_client() (aucun mock, fakes purs + injection de dépendance) :
  (i)   un run crashé sans callback est « interrompu » et PAS auto-reworké ;
  (ii)  GET /api/conversations/interrupted liste ces interrompus (et exclut fin propre) ;
  (iii) POST /api/conversations/<id>/relaunch relance (nouvel agent) ; 404 si inconnu ;
  (iv)  une fin propre (final_answer + verdict disque) est auto-réconciliée sans callback
        et EXCLUE des interrompus.
"""
from __future__ import annotations

import json

import pytest

from bouzecode.web_v2.runtime.runner import Agent


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
    from bouzecode.web_v2.services.sessions.store import runner as _runner

    monkeypatch.setattr(store, "DAILY_DIR", tmp_path / "no_daily")
    monkeypatch.setattr(store, "CACHE_PATH", tmp_path / "cache.json")
    monkeypatch.setattr(_runner, "list_agents",
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
    resp = client.get("/api/conversations/interrupted")
    assert resp.status_code == 200
    body = resp.get_json()
    keys = [c["key"] for c in body["conversations"]]
    assert "agent/crashaaaa0001" in keys
    assert "agent/cleanbbbb0002" not in keys
    item = next(c for c in body["conversations"] if c["key"] == "agent/crashaaaa0001")
    assert item["agent_id"] == "crashaaaa0001"


# (iii) POST relaunch → nouvel agent ; 404 si inconnu
def test_relaunch_spawns_new_agent(client, agents, monkeypatch):
    from bouzecode.web_v2.services.sessions import recovery

    old = agents["crashed"]
    monkeypatch.setattr(recovery.runner, "load_agent",
                        lambda aid: old if aid == old.agent_id else None)

    # relaunch doit re-homer AVANT de resumer (comme /continue), sinon un worktree fauché
    # ressuscite l'agent dans un dossier vide. On trace l'ordre des appels.
    from bouzecode.web_v2.services.work import dispatch
    order = []
    monkeypatch.setattr(dispatch, "rehome_agent_cwd",
                        lambda a: order.append("rehome"))

    def _fake_resume(old_agent, prompt, model=""):
        order.append("resume")
        return Agent(
            agent_id="newagent0003",
            prompt=prompt, model=old_agent.model, cwd=old_agent.cwd,
            pid=0, started_at="2026-07-01T11:00:00Z",
            stdout_path="", session_path="", ipc_dir="",
        )
    monkeypatch.setattr(recovery.runner, "resume_agent", _fake_resume)

    resp = client.post("/api/conversations/crashaaaa0001/relaunch",
                       json={})
    assert resp.status_code == 200
    assert resp.get_json() == {
        "ok": True, "agent_id": "newagent0003", "key": "agent/newagent0003",
    }
    assert "newagent0003" != old.agent_id
    assert order == ["rehome", "resume"]  # re-home STRICTEMENT avant le resume


def test_relaunch_unknown_returns_404(client, monkeypatch):
    from bouzecode.web_v2.services.sessions import recovery

    monkeypatch.setattr(recovery.runner, "load_agent", lambda aid: None)
    resp = client.post("/api/conversations/inexistant/relaunch", json={})
    assert resp.status_code == 404
    assert "error" in resp.get_json()


# (iv) fin propre auto-réconciliée sans callback + exclue des interrompus
def test_clean_finish_auto_reconciled_no_callback(client, agents, tmp_path, monkeypatch):
    from bouzecode.web_v2.services.sessions import recovery, store
    from bouzecode.web_v2.services.work import tickets

    # exclue des interrompus
    resp = client.get("/api/conversations/interrupted")
    keys = [c["key"] for c in resp.get_json()["conversations"]]
    assert "agent/cleanbbbb0002" not in keys

    clean_item = next(a for a in store.list_sessions()["agents"]
                      if a["key"] == "agent/cleanbbbb0002")
    assert clean_item["close_reason"] == "final_answer"
    assert recovery.is_interrupted(clean_item) is False

    # auto-réconciliation du verdict SUR DISQUE (sans callback réseau) :
    # refresh_verdicts relève le VERDICT: OK écrit dans la session.
    slug = "test-recovery-slug"
    ticket = {
        "id": "t1", "title": "démo", "runs": [{
            "agent_id": "cleanbbbb0002", "kind": "validate", "model": "test-model",
            "started_at": "2026-07-01T10:00:00Z", "verdict": None, "typology": "",
        }],
    }
    ticket_list = [ticket]

    # Les deux substitutions passent par `monkeypatch` : une affectation directe sur le
    # module ne revient JAMAIS. `tickets._save` remplacé à la main restait un no-op pour
    # tout le reste du worker pytest, si bien que le store SQLite n'enregistrait plus rien
    # — invisible tant que ce fichier tournait seul, révélé dès que d'autres tests de
    # tickets ont partagé le même worker.
    saved: dict = {}
    monkeypatch.setattr(tickets.runner, "load_agent",
                        lambda aid: agents["clean"] if aid == "cleanbbbb0002" else None)
    monkeypatch.setattr(tickets, "_save", lambda s, t: saved.update({s: t}))

    tickets.refresh_verdicts(slug, ticket_list)

    assert ticket["runs"][0]["verdict"] == "OK"
