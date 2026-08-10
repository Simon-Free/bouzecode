"""Un agent qui attend une réponse humaine est IMPOSSIBLE à rater.

Cas vécu (manager 0123456789ab) : l'agent pose une question, le process quitte, et 900 s
plus tard `repl._resume_paused_warm` écrase l'état IPC `awaiting_input` par un `finished`
nu. Passé ce quart d'heure l'agent était indistinguable d'un agent terminé — plus d'état
d'attente, plus de question, plus d'options — et un archivage suffisait à le faire
disparaître de l'arbre. Il a attendu plus d'une heure sans que rien ne le signale.

Ce qu'on prouve ici, du point de vue de qui regarde l'UI :
  * la question survit à l'effacement de l'IPC (elle est sur disque) ;
  * l'agent est reconnaissable comme « en attente », question ET options exposées ;
  * un agent sans question n'annonce aucune question ;
  * archivé mais vivant, il reste visible.
"""
import json
import os

import pytest


def _write_agent(agents_dir, agent_id, *, ipc_status="finished", running=False,
                 question=None, options=None, allow_freetext=True, prompt=None):
    """Un agent web sur disque. `question` non nul → une question SANS RÉPONSE sur disque
    (`<session>.pending.json`), exactement ce qu'écrit `repl._persist_pause_and_exit`."""
    session_path = agents_dir / f"{agent_id}.session.json"
    (agents_dir / f"{agent_id}.json").write_text(json.dumps({
        "agent_id": agent_id,
        "prompt": prompt or f"Conversation {agent_id}",
        "model": "claude-sonnet",
        "cwd": "/tmp",
        "pid": os.getpid() if running else 999_999_999,
        "started_at": "2026-07-27T13:16:36Z",
        "returncode": None if running else 0,
        "session_path": str(session_path),
        "stdout_path": str(agents_dir / f"{agent_id}.out.log"),
        "ipc_dir": str(agents_dir / f"{agent_id}.ipc"),
    }), encoding="utf-8")
    session_path.write_text(json.dumps({"messages": [], "close_reason": "final_answer"}),
                            encoding="utf-8")
    ipc = agents_dir / f"{agent_id}.ipc"
    ipc.mkdir(parents=True, exist_ok=True)
    # L'IPC APRÈS la TTL de 900 s : un `finished` nu, sans question ni close_reason.
    (ipc / "state.json").write_text(
        json.dumps({"status": ipc_status, "updated_at": 1785235352.99, "turn": 32}),
        encoding="utf-8")
    if question is not None:
        (agents_dir / f"{agent_id}.session.json.pending.json").write_text(json.dumps({
            "ask_tc_id": "ask_1",
            "question": question,
            "options": options or [],
            "allow_freetext": allow_freetext,
            "completed_results": {},
            "pending_tcs": [],
        }, ensure_ascii=False), encoding="utf-8")


BLOQUE = "0123456789ab"   # le manager du cas vécu
FINI = "abcdef123456"
QUESTION = "Le canal de dispatch est bloqué : je relance ou j'abandonne ?"
OPTIONS = [{"label": "Relancer", "description": "3e tentative"},
           {"label": "Abandonner", "description": "Escalade"}]


@pytest.fixture()
def agents_dir(tmp_path, monkeypatch):
    from bouzecode.web_v2.runtime import runner
    from bouzecode.web_v2.services.sessions import purge, store

    d = tmp_path / "web_agents"
    d.mkdir()
    monkeypatch.setattr(runner, "AGENTS_DIR", d)
    monkeypatch.setattr(purge, "TRASH_DIR", d / "_trash")
    monkeypatch.setattr(purge, "DELETED_PATH", tmp_path / "deleted_sessions.json")
    monkeypatch.setattr(store, "_status_cache", {})
    runner._list_agents_cache.clear()
    runner._ipc_state_cache.clear()

    _write_agent(d, BLOQUE, question=QUESTION, options=OPTIONS, allow_freetext=False,
                 prompt="Intégration de la stratégie initiale")
    _write_agent(d, FINI)  # a livré, n'attend personne
    runner._list_agents_cache.clear()
    return d


@pytest.fixture()
def client(agents_dir):
    from bouzecode.web_v2.app import create_app

    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_the_question_outlives_the_erased_ipc_state(client):
    """L'IPC dit « finished », et pourtant l'agent est annoncé en attente, question comprise."""
    resp = client.get("/api/agents/awaiting")
    assert resp.status_code == 200
    agents = {a["agent_id"]: a for a in resp.get_json()["agents"]}

    assert BLOQUE in agents, "l'agent bloqué sur une question est introuvable"
    assert agents[BLOQUE]["state"] == "awaiting_input"
    assert agents[BLOQUE]["question"] == QUESTION
    assert [o["label"] for o in agents[BLOQUE]["options"]] == ["Relancer", "Abandonner"]


def test_an_agent_with_no_question_announces_none(client):
    """Un agent qui a livré n'apparaît pas dans la liste des attentes."""
    agents = client.get("/api/agents/awaiting").get_json()["agents"]

    assert FINI not in [a["agent_id"] for a in agents]
    blocs = client.get(f"/api/sessions/agent/{FINI}/blocks").get_json()
    assert blocs["status"]["state"] == "finished"
    assert blocs["status"]["question"] == ""
    assert blocs["status"]["options"] == []


def test_allow_freetext_reports_the_real_constraint(client):
    """`allow_freetext` dit ce que la question autorise vraiment, il ne vaut pas True partout."""
    agents = {a["agent_id"]: a for a in client.get("/api/agents/awaiting").get_json()["agents"]}

    assert agents[BLOQUE]["allow_freetext"] is False


def test_an_awaiting_agent_is_not_labelled_running(client):
    """La vivacité distingue « attend une réponse » de « travaille » : deux gestes différents."""
    from bouzecode.web_v2.runtime import runner
    from bouzecode.web_v2.services.sessions import store
    from bouzecode.web_v2.services.work import liveness

    agent = runner.load_agent(BLOQUE)
    etat = store.agent_status(agent)["state"]

    assert liveness.classify_agent(agent, etat) == "awaiting_input"
    assert liveness.classify_agent(runner.load_agent(FINI), "finished") == "delivered"


def test_archiving_never_hides_an_agent_that_is_still_waiting(client, agents_dir):
    """Archivé mais toujours en attente : il reste listé — un drapeau ne fait pas taire une question."""
    from bouzecode.web_v2.services.sessions import purge

    purge.mark_deleted("agent/" + BLOQUE, reason="archived")
    purge.mark_deleted("agent/" + FINI, reason="archived")

    listing = client.get("/api/sessions").get_json()["agents"]
    par_cle = {row["key"]: row for row in listing}

    assert "agent/" + BLOQUE in par_cle, "un agent en attente a disparu de la liste"
    assert par_cle["agent/" + BLOQUE]["archived"] is True
    assert par_cle["agent/" + BLOQUE]["need_input"] is True
    assert "agent/" + FINI not in par_cle  # terminé ET archivé : rangé pour de bon


@pytest.fixture(autouse=True)
def _caches_neufs():
    """Deux caches de PROCESS, sans clé sur le parc d'agents : l'arbre de flotte (10 s) et
    la liste d'agents (3 s). Un test qui les remplit sert sa photo au test suivant, dont
    les agents sont ailleurs. On les vide AVANT (voir la photo de maintenant) et APRÈS
    (ne pas laisser sa photo aux voisins)."""
    from bouzecode.web_v2.runtime import runner
    from bouzecode.web_v2.services.work import fleet

    fleet.clear_tree_cache()
    runner._list_agents_cache.clear()
    yield
    fleet.clear_tree_cache()
    runner._list_agents_cache.clear()


def _tree(client):
    from bouzecode.web_v2.services.work import fleet

    fleet.clear_tree_cache()  # le tree est caché 10 s : on veut la photo de MAINTENANT
    return {n["agent_id"]: n for n in client.get("/api/agents/tree").get_json()["nodes"]}


def test_the_fleet_tree_shows_the_waiting_agent_and_its_question(client):
    """Dans l'arbre de flotte, l'agent bloqué porte son état, sa question et ses options."""
    noeuds = _tree(client)

    assert noeuds[BLOQUE]["state"] == "awaiting_input"
    assert noeuds[BLOQUE]["liveness"] == "awaiting_input"
    assert noeuds[BLOQUE]["question"] == QUESTION
    assert [o["label"] for o in noeuds[BLOQUE]["options"]] == ["Relancer", "Abandonner"]
    assert noeuds[BLOQUE]["allow_freetext"] is False


def test_a_node_without_a_question_carries_no_answer_constraint(client):
    """Un nœud sans question n'annonce ni question, ni options, ni `allow_freetext`."""
    noeuds = _tree(client)

    assert noeuds[FINI]["question"] == ""
    assert noeuds[FINI]["options"] == []
    assert "allow_freetext" not in noeuds[FINI], "champ constant : du bruit qui ressemble à un signal"


def test_the_tree_keeps_an_archived_agent_that_is_still_waiting(client):
    """Archiver ne fait pas disparaître de l'arbre un agent à qui l'on doit une réponse."""
    from bouzecode.web_v2.services.sessions import purge

    purge.mark_deleted("agent/" + BLOQUE, reason="archived")
    purge.mark_deleted("agent/" + FINI, reason="archived")
    noeuds = _tree(client)

    assert BLOQUE in noeuds, "un agent en attente a disparu de l'arbre de flotte"
    assert FINI not in noeuds  # terminé ET archivé : rangé pour de bon
