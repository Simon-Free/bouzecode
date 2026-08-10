# [desc] Un agent tué cesse d'attendre — celui qui a juste expiré son TTL, non. [/desc]
"""`<session>.pending.json` n'est supprimé que lorsque l'agent REÇOIT sa réponse. Un agent
tué ne répond jamais : son marqueur survit et le déclarait « en attente » indéfiniment
(cas vécu `63cd2c4183e8`, tué, encore listé le lendemain avec sa question).

Le critère n'est PAS « le process est-il vivant ? » — ce serait détruire la raison d'être
de la lecture du marqueur : un agent en pause meurt de lui-même au bout de 900 s et doit
rester visible. Ce n'est pas non plus « `finished` sans `close_reason` » : mesuré sur le
parc réel, l'agent tué porte exactement cette signature (il était mort de son TTL avant
qu'on le tue). Le critère retenu est ce qui prouve que plus personne n'est attendu :
une réponse DÉJÀ reçue, ou un arrêt DEMANDÉ.

Le test qui compte le plus est `test_a_long_pause_is_still_a_pause` : il garde le
correctif de visibilité contre son propre remède.
"""
import json
import os

import pytest

QUESTION = "Je relance le validateur ou j'abandonne ?"
ASK_ID = "q1"


def _write_paused_agent(agents_dir, agent_id, *, resolu=False, cancel=False, running=False,
                        session_apres=False):
    """Agent mis en pause sur une question (marqueur pendant sur disque), process mort.

    `resolu` : la session porte DÉJÀ le résultat de la question (réponse arrivée).
    `cancel` : quelqu'un a demandé l'arrêt (`cancel.flag`, écrit par `runner.kill_agent`).
    `session_apres` : la session a été réécrite APRÈS la mise en pause."""
    session_path = agents_dir / f"{agent_id}.session.json"
    (agents_dir / f"{agent_id}.json").write_text(json.dumps({
        "agent_id": agent_id, "prompt": f"Conversation {agent_id}", "model": "opus",
        "cwd": "/tmp", "pid": os.getpid() if running else 999_999_999,
        "started_at": "2026-07-28T15:16:48Z", "returncode": None if running else 0,
        "run_kind": "work", "session_path": str(session_path),
        "stdout_path": str(agents_dir / f"{agent_id}.out.log"),
        "ipc_dir": str(agents_dir / f"{agent_id}.ipc"),
    }), encoding="utf-8")
    messages = [{"role": "user", "content": "vas-y"}]
    if resolu:
        messages.append({"role": "tool", "tool_call_id": ASK_ID,
                         "name": "AskUserQuestion", "content": "relance"})
    session_path.write_text(json.dumps({
        "messages": messages,
        # Clôture délibérée quand la réponse est arrivée et que l'agent a fini son travail.
        "close_reason": "final_answer" if resolu else "",
    }), encoding="utf-8")
    ipc = agents_dir / f"{agent_id}.ipc"
    ipc.mkdir(parents=True, exist_ok=True)
    # L'IPC APRÈS les 900 s d'attente : un `finished` NU, sans close_reason. Signature
    # identique pour l'agent qui attend encore et pour celui qu'on a tué ensuite.
    (ipc / "state.json").write_text(
        json.dumps({"status": "finished", "updated_at": 1785253015.93, "turn": 4}),
        encoding="utf-8")
    if cancel:
        (ipc / "cancel.flag").write_text("", encoding="utf-8")
    marker = agents_dir / f"{agent_id}.session.json.pending.json"
    marker.write_text(json.dumps({
        "ask_tc_id": ASK_ID, "question": QUESTION, "options": [],
        "allow_freetext": True, "completed_results": {}, "pending_tcs": [],
    }, ensure_ascii=False), encoding="utf-8")
    if session_apres:
        # Réécrite après la pause : c'est ce qui autorise à chercher la réponse dedans.
        os.utime(session_path, (marker.stat().st_mtime + 60, marker.stat().st_mtime + 60))
    else:
        os.utime(session_path, (marker.stat().st_mtime - 1, marker.stat().st_mtime - 1))


@pytest.fixture(autouse=True)
def _caches_neufs():
    """Caches de PROCESS (liste d'agents 3 s, statut mémorisé) : vidés avant et après."""
    from bouzecode.web_v2.runtime import runner
    from bouzecode.web_v2.services.sessions import store

    runner._list_agents_cache.clear()
    store._status_cache.clear()
    yield
    runner._list_agents_cache.clear()
    store._status_cache.clear()


@pytest.fixture()
def parc(tmp_path, monkeypatch):
    from bouzecode.web_v2.runtime import runner
    from bouzecode.web_v2.services.sessions import purge

    d = tmp_path / "web_agents"
    d.mkdir()
    monkeypatch.setattr(runner, "AGENTS_DIR", d)
    monkeypatch.setattr(purge, "TRASH_DIR", d / "_trash")
    monkeypatch.setattr(purge, "DELETED_PATH", tmp_path / "deleted_sessions.json")
    runner._list_agents_cache.clear()
    runner._ipc_state_cache.clear()
    return d


def _etat(agent_id):
    from bouzecode.web_v2.runtime import runner
    from bouzecode.web_v2.services.sessions import store

    return store.agent_status(runner.load_agent(agent_id))["state"]


def test_a_long_pause_is_still_a_pause(parc):
    """L'agent qui a épuisé ses 900 s d'attente SANS réponse ni arrêt attend toujours.

    Le test à ne jamais laisser tomber : c'est exactement l'agent que le correctif de
    visibilité existe pour montrer, et son IPC est indistinguable de celui d'un agent tué."""
    _write_paused_agent(parc, "63343a4b4a4a")

    assert _etat("63343a4b4a4a") == "awaiting_input"


def test_a_killed_agent_stops_waiting(parc):
    """Un agent tué (`cancel.flag`) n'attend plus personne, marqueur ou pas."""
    _write_paused_agent(parc, "63cd2c4183e8", cancel=True)

    assert _etat("63cd2c4183e8") == "finished"


def test_a_question_already_answered_stops_waiting(parc):
    """La réponse est DÉJÀ dans la session : le marqueur n'est qu'un résidu."""
    _write_paused_agent(parc, "47117594e206", resolu=True, session_apres=True)

    assert _etat("47117594e206") == "finished"


def test_a_later_session_without_the_answer_keeps_waiting(parc):
    """Session réécrite depuis la pause mais SANS le résultat de la question : il attend.

    Une clôture qui ne répond pas à la question ne vaut pas réponse — sinon un agent
    clos pour une autre raison emporterait avec lui une question restée sans réponse."""
    _write_paused_agent(parc, "5de65ff25336", session_apres=True)

    assert _etat("5de65ff25336") == "awaiting_input"


def test_a_killed_agent_leaves_no_pending_marker_behind(parc):
    """`kill_agent` emporte le marqueur ET garde la session valide pour l'API.

    Nettoyer à la source empêche le mensonge de naître ; le filtre de lecture, lui, reste
    nécessaire pour les marqueurs déjà orphelins (97 sur le poste) et pour les morts
    survenues hors de ce chemin."""
    from bouzecode.web_v2.runtime import pending, runner

    _write_paused_agent(parc, "abcdef123456")
    agent = runner.load_agent("abcdef123456")

    runner.kill_agent(agent)

    assert not pending.exists(agent.session_path), "le marqueur de question a survécu au kill"
    session = json.loads(open(agent.session_path, encoding="utf-8").read())
    resolus = [m for m in session["messages"] if m.get("tool_call_id") == ASK_ID]
    assert resolus and resolus[0]["content"] == "(cancelled by user)"
    assert _etat("abcdef123456") == "finished"
