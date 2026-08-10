# [desc] /interrupt ne doit pas TUER un agent qui a cédé : un agent chaud garde son process. [/desc]
"""Interrompre ne doit pas coûter un cold-start.

Cas vécu (31/07) : dans une conversation web_v2, Ctrl+C — ou l'envoi d'un nouveau message,
qui interrompt puis reboucle sur /continue — mettait « plein de temps », là où le même geste
est immédiat dans le TUI.

La cause n'était pas l'annulation elle-même : `cancel.flag` est consommé en ≤0,2 s pendant le
streaming. C'était l'ESCALADE. `/interrupt` décidait de tuer sur `is_running` — pid vivant —
alors qu'un agent chaud est CONÇU pour survivre à son tour (`run_agent_event_loop` écrit
`idle` puis sonde `followup.txt`). Le pid existait donc toujours après une annulation
parfaitement réussie : le process était tué à TOUS LES COUPS, et le message suivant repartait
en cold-respawn — process neuf, imports, contexte entier réémis — au lieu du `followup.txt`
poussé dans un process vivant.

Ce qu'on prouve ici, du point de vue de qui appuie sur Ctrl+C :
  * un agent qui a cédé (IPC `idle`) garde son process, et l'API l'avoue (`escalated: False`) ;
  * il reste joignable à CHAUD juste après : le message atteint le process vivant ;
  * un agent qui TIENT toujours son tour (IPC `running`) est bien escaladé — la porte de
    sortie contre un agent coincé hors point d'interruption n'a pas été refermée.

Aucun process RÉEL n'est visé : les pid vivants sont des `sleep` fabriqués par ce test, tués
par lui à la fin.
"""
import json
import subprocess
import sys

import pytest

CEDE = "eeee5555ffff"      # a lâché son tour : IPC idle, process encore là (warm pool)
COINCE = "9999aaaa8888"    # tient toujours son tour : IPC running, ne verra jamais le flag


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
        "prompt": "Ok tier",
        "model": "claude-sonnet",
        "cwd": str(agents_dir),
        "pid": pid,
        "started_at": "2026-07-31T10:00:00Z",
        "returncode": None,
        "session_path": str(session_path),
        "stdout_path": str(agents_dir / f"{agent_id}.out.log"),
        "ipc_dir": str(agents_dir / f"{agent_id}.ipc"),
    }), encoding="utf-8")
    session_path.write_text(json.dumps({"messages": [{"role": "user", "content": "Ok tier"}]}),
                            encoding="utf-8")
    ipc = agents_dir / f"{agent_id}.ipc"
    ipc.mkdir(parents=True, exist_ok=True)
    # Exactement ce qu'écrit `ipc.run_agent_event_loop` : STATUS_IDLE une fois le tour rendu,
    # STATUS_RUNNING pendant le tour.
    (ipc / "state.json").write_text(
        json.dumps({"status": ipc_status, "updated_at": 1785342082.9, "turn": 3}),
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

    pid_cede, pid_coince = processus_jetables
    _ecrire_agent(d, CEDE, pid=pid_cede, ipc_status="idle")
    _ecrire_agent(d, COINCE, pid=pid_coince, ipc_status="running")
    runner._list_agents_cache.clear()
    return d


@pytest.fixture()
def client(agents_dir):
    from bouzecode.web_v2.app import create_app

    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


# ── un agent qui a cédé garde son process ────────────────────────────────────

def test_interrupting_an_agent_that_gave_up_does_not_kill_it(client, agents_dir):
    """Le cœur du bug : l'annulation a réussi, il n'y a plus rien à tuer."""
    import psutil
    from bouzecode.web_v2.runtime import runner

    pid_avant = runner.load_agent(CEDE).pid

    reponse = client.post(f"/api/agents/{CEDE}/interrupt")

    assert reponse.status_code == 200
    assert reponse.get_json() == {"ok": True, "escalated": False}, \
        "un agent chaud qui a cédé se fait encore tuer par l'escalade"
    assert psutil.pid_exists(pid_avant), "le process a été tué alors qu'il avait obéi"


def test_the_soft_flag_is_posted_even_when_nothing_is_escalated(client, agents_dir):
    """L'interruption douce reste faite : c'est elle qui arrête le tour suivant."""
    from bouzecode.web_v2.runtime import ipc

    client.post(f"/api/agents/{CEDE}/interrupt")

    assert ipc.is_cancelled(ipc.from_dir(str(agents_dir / f"{CEDE}.ipc"))) is True


def test_the_agent_is_still_reachable_hot_right_after(client, agents_dir):
    """La conséquence qui se voit : le message suivant atteint le process VIVANT.

    C'est tout l'écart de temps ressenti — `followup.txt` poussé dans un process résident,
    au lieu d'un respawn qui réémet le contexte entier avant le premier jeton."""
    from bouzecode.web_v2.runtime import runner

    pid_avant = runner.load_agent(CEDE).pid
    client.post(f"/api/agents/{CEDE}/interrupt")

    reponse = client.post(f"/api/agents/{CEDE}/continue", json={"text": "en fait, plutôt X"})

    assert reponse.status_code == 200, reponse.get_json()
    followup = agents_dir / f"{CEDE}.ipc" / "followup.txt"
    assert followup.read_text(encoding="utf-8") == "en fait, plutôt X"
    assert runner.load_agent(CEDE).pid == pid_avant, "l'agent a été respawné à froid"


# ── NON-RÉGRESSION : un agent coincé est toujours escaladé ───────────────────

def test_an_agent_still_holding_its_turn_is_still_escalated(client):
    """La porte de sortie tient : un agent qui ne cède pas finit par être tué."""
    reponse = client.post(f"/api/agents/{COINCE}/interrupt")

    assert reponse.status_code == 200
    assert reponse.get_json()["escalated"] is True, \
        "un agent coincé hors point d'interruption n'est plus escaladé — il devient injoignable"


def test_who_gave_up_is_read_from_the_turn_not_from_the_pid(agents_dir):
    """Le prédicat lui-même : deux process également VIVANTS, un seul tient son tour."""
    from bouzecode.web_v2.runtime import runner

    assert runner.is_running(runner.load_agent(CEDE)) is True, "prémisse : le process est vivant"
    assert runner.is_mid_turn(runner.load_agent(CEDE)) is False
    assert runner.is_mid_turn(runner.load_agent(COINCE)) is True
