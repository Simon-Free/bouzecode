"""Un agent CHAUD dont l'IPC dit `finished` reste joignable : le follow-up part.

Cas vécu : l'agent rend une FinalAnswer. Son process warm-pool
est encore VIVANT (le hook on_completion / le test-gate tourne, ou le process n'a pas
encore rebouclé vers `idle`), et son IPC porte `finished`. L'utilisateur envoie un
follow-up dans le panneau de conversation : clic « Envoyer » → RIEN. Pas de loader,
pas de réaction de l'agent, pas d'erreur, silence total.

Cause : `_is_warm` n'accepte QUE le status IPC `idle`. Un process vivant en état
transitoire `finished` (post-FinalAnswer, avant re-bouclage warm) était déclaré
NON-chaud → `continue_agent` partait sur le chemin FROID `_respawn`, lequel REFUSE de
lancer un jumeau tant qu'un process vit pour la session (garde anti-double-spawn) →
`return None`. Résultat : `followup.txt` n'est JAMAIS écrit, aucun tour n'est joué, et
l'endpoint renvoie tout de même 200 {ok:True}. Trou noir : ni chaud (finished≠idle),
ni froid (respawn refusé car vivant).

Ce qu'on prouve, du point de vue de qui écrit à l'agent : un message ATTEINT un agent
chaud dont l'IPC dit `finished` (process vivant), et il l'atteint par la reprise CHAUDE
(in-process, pid inchangé) — exactement comme pour un agent `idle`.

Aucun process RÉEL n'est visé : le pid vivant est un `sleep` fabriqué par ce test, tué
par lui à la fin.
"""
import json
import subprocess
import sys

import pytest

FINI_MAIS_VIVANT = "eeee3333ffff"  # a rendu FinalAnswer, process warm encore vivant


@pytest.fixture()
def processus_jetable():
    """Un process bien VIVANT, créé et tué par ce test — jamais un agent réel."""
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(300)"])
    yield proc.pid
    proc.kill()
    proc.wait(timeout=10)


def _ecrire_agent(agents_dir, agent_id, *, pid, ipc_status):
    """Un agent web sur disque, au process VIVANT, dont l'IPC porte `ipc_status`."""
    session_path = agents_dir / f"{agent_id}.session.json"
    (agents_dir / f"{agent_id}.json").write_text(json.dumps({
        "agent_id": agent_id,
        "prompt": f"Conversation {agent_id}",
        "model": "claude-sonnet",
        "cwd": str(agents_dir),
        "pid": pid,
        "started_at": "2026-07-31T11:00:00Z",
        "returncode": None,
        "session_path": str(session_path),
        "stdout_path": str(agents_dir / f"{agent_id}.out.log"),
        "ipc_dir": str(agents_dir / f"{agent_id}.ipc"),
    }), encoding="utf-8")
    session_path.write_text(json.dumps({"messages": [{"role": "user", "content": "salut"}]}),
                            encoding="utf-8")
    ipc = agents_dir / f"{agent_id}.ipc"
    ipc.mkdir(parents=True, exist_ok=True)
    (ipc / "state.json").write_text(
        json.dumps({"status": ipc_status, "updated_at": 1785342082.9, "turn": 65}),
        encoding="utf-8")


@pytest.fixture()
def agents_dir(tmp_path, monkeypatch, processus_jetable):
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

    _ecrire_agent(d, FINI_MAIS_VIVANT, pid=processus_jetable, ipc_status="finished")
    runner._list_agents_cache.clear()
    return d


@pytest.fixture()
def client(agents_dir):
    from bouzecode.web_v2.app import create_app

    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


@pytest.fixture(autouse=True)
def _caches_neufs():
    from bouzecode.web_v2.runtime import runner
    from bouzecode.web_v2.services.work import fleet

    fleet.clear_tree_cache()
    runner._list_agents_cache.clear()
    yield
    fleet.clear_tree_cache()
    runner._list_agents_cache.clear()


def test_a_message_reaches_a_finished_but_alive_warm_agent(client, agents_dir):
    """Écrire à un agent chaud dont l'IPC dit `finished` marche : le texte part vraiment."""
    resp = client.post(f"/api/agents/{FINI_MAIS_VIVANT}/continue", json={"text": "reprends stp"})

    assert resp.status_code == 200, resp.get_json()
    followup = agents_dir / f"{FINI_MAIS_VIVANT}.ipc" / "followup.txt"
    assert followup.exists(), (
        "le follow-up n'a atteint aucun canal : trou noir post-FinalAnswer "
        "(ni chaud car IPC=finished, ni froid car respawn refusé — process vivant)"
    )
    assert followup.read_text(encoding="utf-8") == "reprends stp"


def test_the_message_is_handed_to_the_living_process_not_a_respawn(client, agents_dir):
    """Reprise CHAUDE : le process vivant garde son pid, aucun cold-start ne le remplace."""
    from bouzecode.web_v2.runtime import runner

    pid_avant = runner.load_agent(FINI_MAIS_VIVANT).pid
    client.post(f"/api/agents/{FINI_MAIS_VIVANT}/continue", json={"text": "suite"})

    assert runner.load_agent(FINI_MAIS_VIVANT).pid == pid_avant, (
        "l'agent a été respawné au lieu d'être réveillé"
    )
