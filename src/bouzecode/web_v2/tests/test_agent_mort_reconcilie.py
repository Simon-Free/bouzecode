"""Un agent dont le process n'existe plus ne reste jamais « en cours ».

Cas vécu sur le serveur d'essai (24/09) : deux agents tués (0149e917041b figé à 10:30,
058a8c13bcbc tué par SIGTERM à 18:47) gardaient `status: running` dans leur `state.json`.
Un agent tué ne peut pas corriger son IPC : c'est au serveur de CONSTATER la mort, avec une
raison lisible, au boot comme en cours de route — sans jamais tuer ni relancer quoi que ce soit.

Vrais sous-processus : on les tue nous-mêmes, puis on regarde ce que le serveur en dit.
"""
from __future__ import annotations

import json
import signal
import subprocess
import sys
import time
from datetime import datetime

import psutil
import pytest

from bouzecode.web_v2.runtime.runner import agent_etat, agent_fiche, agent_registre, agent_vivacite
from bouzecode.web_v2.services.sessions import store
from bouzecode.web_v2.services.work import liveness
from bouzecode.web_v2.tests.production_isolation import isoler_le_parc_d_agents

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="signaux POSIX")


@pytest.fixture
def parc(tmp_path, monkeypatch):
    return isoler_le_parc_d_agents(tmp_path, monkeypatch)


@pytest.fixture
def lances():
    """Sous-processus du test : tous tués et ramassés à la fin, quoi qu'il arrive."""
    procs: list[subprocess.Popen] = []
    yield procs
    for proc in procs:
        if proc.poll() is None:
            proc.kill()
        proc.wait(timeout=10)


def _lancer(lances, session_path) -> subprocess.Popen:
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)",
                             "--session-file", str(session_path)])
    lances.append(proc)
    return proc


def _fiche(parc, agent_id: str, proc: subprocess.Popen, **champs) -> agent_fiche.Agent:
    """Écrit la fiche d'un agent EN COURS (rc inconnu) et son IPC figé sur `running`."""
    ipc_dir = parc / f"{agent_id}.ipc"
    ipc_dir.mkdir()
    (ipc_dir / "state.json").write_text(
        json.dumps({"status": "running", "updated_at": 1.0, "turn": 10}), encoding="utf-8")
    data = {
        "agent_id": agent_id, "prompt": "travaille", "model": "m", "cwd": str(parc),
        "pid": proc.pid, "started_at": datetime.utcnow().isoformat() + "Z",
        "returncode": None, "session_path": str(parc / f"{agent_id}.session.json"),
        "ipc_dir": str(ipc_dir), "pid_create_time": psutil.Process(proc.pid).create_time(),
        **champs,
    }
    (parc / f"{agent_id}.json").write_text(json.dumps(data), encoding="utf-8")
    return agent_fiche.load_agent(agent_id)


def _vu_par_le_bureau(agent_id: str) -> tuple[str, str]:
    agent = agent_fiche.load_agent(agent_id)
    etat = store.agent_status(agent)["state"]
    return etat, liveness.classify_agent(agent)


def test_un_agent_vivant_reste_en_cours(parc, lances):
    proc = _lancer(lances, parc / "vif.session.json")
    _fiche(parc, "a1b2c3d4e5f6", proc)

    assert _vu_par_le_bureau("a1b2c3d4e5f6")[1] == "running"
    assert agent_fiche.load_agent("a1b2c3d4e5f6").returncode is None


def test_agent_tue_en_cours_de_route_passe_arrete_avec_sa_raison(parc, lances):
    proc = _lancer(lances, parc / "tue.session.json")
    _fiche(parc, "0149e917041b", proc)
    assert agent_vivacite.is_running(agent_fiche.load_agent("0149e917041b"))

    proc.send_signal(signal.SIGTERM)
    _attendre_la_mort(proc.pid)  # zombie : son parent (le serveur, ici nous) ne l'a pas ramassé

    assert _vu_par_le_bureau("0149e917041b") == ("finished", "crashed")
    agent = agent_fiche.load_agent("0149e917041b")
    assert agent.returncode == -signal.SIGTERM
    assert agent.fin_constatee == "processus tué par SIGTERM"
    #  La raison montrée par le Bureau pour un ticket arrêté porte le constat du serveur.
    from bouzecode.web_v2.services.work.taches_passage import raison_d_echec
    arrete = {"state": "stopped", "state_reason": {"code": "crashed"}}
    assert "SIGTERM" in raison_d_echec(arrete, agent)
    # Observer n'est pas réécrire : l'IPC de l'agent est laissé tel qu'il l'a écrit.
    ipc = json.loads((parc / "0149e917041b.ipc" / "state.json").read_text(encoding="utf-8"))
    assert ipc["status"] == "running"


def test_agent_mort_pendant_l_arret_du_serveur_est_constate_au_boot(parc, lances):
    proc = _lancer(lances, parc / "boot.session.json")
    _fiche(parc, "058a8c13bcbc", proc)
    proc.terminate()
    proc.wait(timeout=10)  # ramassé : le pid n'existe plus du tout

    assert agent_registre.reconcile_dead_agents() == ["058a8c13bcbc"]

    agent = agent_fiche.load_agent("058a8c13bcbc")
    assert agent.returncode == -1
    assert agent.fin_constatee == (
        f"processus disparu (pid {proc.pid}) — constaté au démarrage du serveur")
    assert _vu_par_le_bureau("058a8c13bcbc") == ("finished", "crashed")


def test_pid_reutilise_par_un_autre_programme_ne_fait_pas_un_agent_vivant(parc, lances):
    """La fiche pointe un pid VIVANT, mais ce n'est plus le process de l'agent (instant de
    création différent). Au boot comme en route : mort constatée, et le programme tiers qui a
    hérité du pid n'est jamais touché."""
    tiers = _lancer(lances, parc / "autre-programme")
    _fiche(parc, "aaaaaaaaaaaa", tiers,
           pid_create_time=psutil.Process(tiers.pid).create_time() - 3600)
    _fiche(parc, "bbbbbbbbbbbb", tiers,
           pid_create_time=psutil.Process(tiers.pid).create_time() - 7200)

    assert not agent_vivacite.is_running(agent_fiche.load_agent("aaaaaaaaaaaa"))
    agent_etat.refresh_agent_status(agent_fiche.load_agent("aaaaaaaaaaaa"))  # en cours de route
    assert agent_registre.reconcile_dead_agents() == ["bbbbbbbbbbbb"]  # au boot

    for agent_id in ("aaaaaaaaaaaa", "bbbbbbbbbbbb"):
        agent = agent_fiche.load_agent(agent_id)
        assert agent.fin_constatee.startswith(f"pid {tiers.pid} réutilisé par un autre programme")
        assert _vu_par_le_bureau(agent_id) == ("finished", "crashed")
    assert tiers.poll() is None  # le tiers tourne toujours


def _attendre_la_mort(pid: int) -> None:
    """Jusqu'à ce que le process soit un zombie (tué, pas encore ramassé)."""
    proc = psutil.Process(pid)
    for _ in range(200):
        if proc.status() == psutil.STATUS_ZOMBIE:
            return
        time.sleep(0.02)
    raise AssertionError("le process n'est pas mort")
