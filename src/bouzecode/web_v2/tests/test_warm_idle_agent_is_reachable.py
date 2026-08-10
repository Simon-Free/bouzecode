"""Un agent CHAUD MAIS OISIF reste joignable, et ne se fait pas passer pour un travailleur.

Cas vécu (manager 0123456789ab, 29/07) : l'agent finit son tour et reste résident dans le
warm pool. Son IPC dit `idle` depuis 18:07:43 — mais un process existe, donc l'API le
déclarait `running`. Conséquence : `POST /api/agents/<id>/continue` répondait 409 « l'agent
tourne encore » à CHAQUE tentative, pendant 20 minutes. Personne — ni l'utilisateur, ni un
autre agent — ne pouvait plus lui parler, alors qu'il ne faisait RIEN ; et l'interface
l'annonçait « en cours », donc on l'a cru au travail. Il a fallu TUER son process pour que
le message passe.

Ce qu'on prouve ici, du point de vue de qui regarde l'UI et de qui écrit à l'agent :
  * un agent dont l'IPC dit `idle` n'est PAS annoncé « en train de travailler » ;
  * un message lui PARVIENT (pas de 409), et par la reprise CHAUDE (in-process) ;
  * un agent RÉELLEMENT en plein tour refuse toujours en 409 — la garde anti-double-tour
    protège encore la session ;
  * l'arbre de flotte ne le montre pas « en cours ».

Aucun process RÉEL n'est visé : les pid vivants sont des `sleep` fabriqués par ce test,
tués par lui à la fin.
"""
import json
import subprocess
import sys

import pytest

OISIF = "aaaa1111bbbb"      # chaud, tour fini : l'agent du cas vécu
AU_TRAVAIL = "cccc2222dddd"  # en plein tour : celui que la garde DOIT protéger


@pytest.fixture()
def processus_jetables():
    """Des process bien VIVANTS, créés et tués par ce test — jamais un agent réel."""
    procs = [subprocess.Popen([sys.executable, "-c", "import time; time.sleep(300)"])
             for _ in range(2)]
    yield [p.pid for p in procs]
    for p in procs:
        p.kill()
        p.wait(timeout=10)


def _ecrire_agent(agents_dir, agent_id, *, pid, ipc_status):
    """Un agent web sur disque, au process VIVANT, dont l'IPC porte `ipc_status`."""
    session_path = agents_dir / f"{agent_id}.session.json"
    (agents_dir / f"{agent_id}.json").write_text(json.dumps({
        "agent_id": agent_id,
        "prompt": f"Conversation {agent_id}",
        "model": "claude-sonnet",
        "cwd": str(agents_dir),
        "pid": pid,
        "started_at": "2026-07-29T18:00:00Z",
        "returncode": None,
        "session_path": str(session_path),
        "stdout_path": str(agents_dir / f"{agent_id}.out.log"),
        "ipc_dir": str(agents_dir / f"{agent_id}.ipc"),
    }), encoding="utf-8")
    session_path.write_text(json.dumps({"messages": [{"role": "user", "content": "salut"}]}),
                            encoding="utf-8")
    ipc = agents_dir / f"{agent_id}.ipc"
    ipc.mkdir(parents=True, exist_ok=True)
    # Exactement ce qu'écrit `ipc.run_agent_event_loop` : STATUS_IDLE en boucle d'attente
    # de followup, STATUS_RUNNING pendant un tour.
    (ipc / "state.json").write_text(
        json.dumps({"status": ipc_status, "updated_at": 1785342082.9, "turn": 65}),
        encoding="utf-8")


@pytest.fixture()
def agents_dir(tmp_path, monkeypatch, processus_jetables):
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

    pid_oisif, pid_au_travail = processus_jetables
    _ecrire_agent(d, OISIF, pid=pid_oisif, ipc_status="idle")
    _ecrire_agent(d, AU_TRAVAIL, pid=pid_au_travail, ipc_status="running")
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
    """L'arbre de flotte (10 s) et la liste d'agents (3 s) sont des caches de PROCESS, sans
    clé sur le parc : un test qui les remplit sert sa photo au suivant."""
    from bouzecode.web_v2.runtime import runner
    from bouzecode.web_v2.services.work import fleet

    fleet.clear_tree_cache()
    runner._list_agents_cache.clear()
    yield
    fleet.clear_tree_cache()
    runner._list_agents_cache.clear()


# ── (a) l'agent oisif n'est pas annoncé « en train de travailler » ────────────

def test_a_warm_idle_agent_is_not_announced_as_working(agents_dir):
    """Process vivant + IPC `idle` : l'agent est dit oisif, jamais « en cours »."""
    from bouzecode.web_v2.runtime import runner
    from bouzecode.web_v2.services.sessions import store

    etat = store.agent_status(runner.load_agent(OISIF))["state"]

    assert etat == "idle", "un agent chaud mais oisif se déclare encore « en train de travailler »"


def test_an_agent_really_mid_turn_is_still_announced_running(agents_dir):
    """Le pendant : IPC `running`, l'agent travaille vraiment et le dit."""
    from bouzecode.web_v2.runtime import runner
    from bouzecode.web_v2.services.sessions import store

    assert store.agent_status(runner.load_agent(AU_TRAVAIL))["state"] == "running"


def test_an_idle_agent_stays_alive_for_every_rule_that_means_dont_touch(agents_dir):
    """Oisif ≠ fini : il tient toujours son worktree, il reste visible, il n'est pas un déchet."""
    from bouzecode.web_v2.services.sessions import purge, visibility
    from bouzecode.web_v2.services.work import isolation, liveness, workflow

    assert "idle" in liveness.ALIVE
    assert "idle" in visibility.ALIVE_STATES
    assert "idle" in purge._ETATS_VIVANTS
    assert "idle" in isolation._ACTIVE_STATES
    assert "idle" in workflow._ACTIVE


# ── (b) un message lui parvient ───────────────────────────────────────────────

def test_a_message_reaches_a_warm_idle_agent(client, agents_dir):
    """Écrire à un agent oisif marche : plus de 409, et le texte part vraiment."""
    resp = client.post(f"/api/agents/{OISIF}/continue", json={"text": "reprends stp"})

    assert resp.status_code == 200, resp.get_json()
    followup = agents_dir / f"{OISIF}.ipc" / "followup.txt"
    assert followup.exists(), "le message n'a atteint aucun canal"
    assert followup.read_text(encoding="utf-8") == "reprends stp"


def test_the_message_is_handed_to_the_living_process_not_a_respawn(client, agents_dir):
    """Reprise CHAUDE : le process vivant garde son pid, aucun cold-start ne le remplace."""
    from bouzecode.web_v2.runtime import runner

    pid_avant = runner.load_agent(OISIF).pid
    client.post(f"/api/agents/{OISIF}/continue", json={"text": "suite"})

    assert runner.load_agent(OISIF).pid == pid_avant, "l'agent a été respawné au lieu d'être réveillé"


# ── (c) NON-RÉGRESSION : un agent en plein tour refuse toujours ───────────────

def test_an_agent_really_mid_turn_still_refuses_a_second_turn(client, agents_dir):
    """La garde anti-double-tour tient : on n'ouvre pas deux tours sur la même session."""
    resp = client.post(f"/api/agents/{AU_TRAVAIL}/continue", json={"text": "et ça ?"})

    assert resp.status_code == 409, "deux tours concurrents sont devenus possibles"
    assert resp.get_json()["reason"] == "running"
    assert not (agents_dir / f"{AU_TRAVAIL}.ipc" / "followup.txt").exists()


# ── (d) l'affichage de flotte dit la vérité ──────────────────────────────────

def test_the_fleet_tree_does_not_show_an_idle_agent_as_running(client):
    """Dans l'arbre de flotte, l'agent oisif porte « chaud », pas « en cours »."""
    from bouzecode.web_v2.services.work import fleet

    fleet.clear_tree_cache()
    noeuds = {n["agent_id"]: n for n in client.get("/api/agents/tree").get_json()["nodes"]}

    assert noeuds[OISIF]["state"] == "idle"
    assert noeuds[OISIF]["liveness"] == "idle", "l'inaction est présentée comme du travail"
    assert noeuds[OISIF]["warm"] is True
    assert noeuds[AU_TRAVAIL]["liveness"] == "running"


def test_the_conversation_panel_agrees_with_the_tree(client):
    """Le panneau de conversation sert la MÊME vivacité que l'arbre — jamais deux vérités."""
    status = client.get(f"/api/sessions/agent/{OISIF}/blocks").get_json()["status"]

    assert status["state"] == "idle"
    assert status["liveness"] == "idle"
    assert status["interrupted"] is False
