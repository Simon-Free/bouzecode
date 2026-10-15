# [desc] Tests du runner web_v2 : lecture des fiches agent sur disque, nettoyage du stdout, statut IPC. [/desc]
"""Le serveur relit les agents posés sur disque, nettoie leur sortie et suit leur statut IPC."""
from __future__ import annotations

import json

import pytest

from bouzecode.web_v2.runtime.runner import agent_fiche, agent_registre
from bouzecode.web_v2.runtime.runner.agent_etat import refresh_agent_status, get_ipc_state
from bouzecode.web_v2.runtime.runner.agent_fiche import Agent


# ── Le parc d'agents relu depuis le disque ─────────────────────────────

VALID_AGENT_DATA = {
    "agent_id": "abc123",
    "prompt": "do stuff",
    "model": "claude-opus-4-6",
    "cwd": "/tmp",
    "pid": 1234,
    "started_at": "2026-04-14T10:00:00Z",
}


@pytest.fixture
def parc(tmp_path, monkeypatch):
    """Un parc d'agents vide ; renvoie une fonction qui y pose des fiches JSON."""
    monkeypatch.setattr(agent_fiche, "AGENTS_DIR", tmp_path)
    agent_fiche._list_agents_cache.clear()

    def poser(nom: str, data) -> None:
        (tmp_path / nom).write_text(json.dumps(data), encoding="utf-8")
        agent_fiche._list_agents_cache.clear()

    return poser


def test_une_fiche_complete_apparait_dans_le_parc_avec_ses_champs(parc):
    parc("abc123.json", {**VALID_AGENT_DATA, "finished_at": "2026-04-14T11:00:00Z",
                         "returncode": 0, "unknown_field": 42})
    [agent] = agent_registre.list_agents()
    assert (agent.agent_id, agent.model, agent.pid) == ("abc123", "claude-opus-4-6", 1234)
    assert (agent.finished_at, agent.returncode) == ("2026-04-14T11:00:00Z", 0)
    assert not hasattr(agent, "unknown_field")


@pytest.mark.parametrize("champ", sorted(agent_fiche._REQUIRED_KEYS))
def test_une_fiche_incomplete_est_ignoree(parc, champ):
    parc("abc123.json", {k: v for k, v in VALID_AGENT_DATA.items() if k != champ})
    assert agent_registre.list_agents() == []


@pytest.mark.parametrize("nom, data", [
    ("abc123.session.json", {"session_id": "477b981b", "saved_at": "x", "messages": []}),
    ("vide.json", {}),
    ("liste.json", [{"id": "q1", "text": "message en file"}]),
], ids=["sidecar-de-session", "json-vide", "json-liste"])
def test_un_json_qui_n_est_pas_une_fiche_d_agent_est_ignore(parc, nom, data):
    parc(nom, data)
    assert agent_registre.list_agents() == []


def test_un_agent_sauve_se_relit_a_l_identique(parc):
    agent_fiche._save(Agent(**VALID_AGENT_DATA))
    relu = agent_fiche.load_agent("abc123")
    assert relu is not None
    assert (relu.agent_id, relu.prompt, relu.started_at) == ("abc123", "do stuff", "2026-04-14T10:00:00Z")


# ── refresh_agent_status: une LECTURE ne tue jamais (spec ticketing B1, constat C2) ─────

def test_refresh_ne_tue_pas_un_process_vivant_dont_l_ipc_dit_finished(tmp_path, monkeypatch):
    """Process vivant + IPC finished = fenêtre reprenable à chaud (`_is_warm`) : la lecture
    laisse le process vivre et ne le marque pas fini. Son éviction relève du pool chaud."""
    import subprocess, sys, os
    from bouzecode.web_v2.runtime.runner import agent_chaud
    from bouzecode.web_v2.tests.production_isolation import autoriser_la_destruction

    monkeypatch.setattr("bouzecode.web_v2.runtime.runner.agent_fiche.AGENTS_DIR", tmp_path)
    # Le process ciblé est fabriqué par ce test : on lève le garde-fou qui rend toute
    # terminaison inerte sous pytest (sans lui, le test attendait 5 s puis échouait).
    autoriser_la_destruction(monkeypatch)

    # Spawn a real subprocess that sleeps forever
    # Le process porte le chemin de session dans sa ligne de commande, comme un vrai agent :
    # c'est la preuve d'identité exigée avant toute terminaison (pid recyclé = jamais tué).
    session_path = tmp_path / "stuck01.session.json"
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(3600)", str(session_path)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )

    ipc_dir = tmp_path / "stuck01.ipc"
    ipc_dir.mkdir()
    # Write IPC state = finished (simulates agent event loop done but process hung)
    (ipc_dir / "state.json").write_text(
        json.dumps({"status": "finished", "updated_at": 0}), encoding="utf-8",
    )

    agent = Agent(
        agent_id="stuck01", prompt="test", model="m", cwd=str(tmp_path),
        pid=proc.pid, started_at="2026-01-01T00:00:00Z",
        stdout_path=str(tmp_path / "stuck01.out.log"),
        session_path=str(session_path),
        ipc_dir=str(ipc_dir),
    )
    (tmp_path / "stuck01.json").write_text(
        json.dumps({"agent_id": "stuck01", "prompt": "test", "model": "m",
                     "cwd": str(tmp_path), "pid": proc.pid,
                     "started_at": "2026-01-01T00:00:00Z"}),
        encoding="utf-8",
    )

    result = refresh_agent_status(agent)
    assert result.returncode is None
    assert proc.poll() is None
    assert agent_chaud.is_warm(agent)
    proc.terminate()
    proc.wait(timeout=5)


def test_identite_prouvee_meme_pendant_l_exec_d_un_agent_qui_vient_de_naitre(monkeypatch):
    """Juste après Popen, /proc/<pid>/cmdline peut être VIDE (exec en cours) : la preuve
    d'identité ne doit pas conclure « pas le nôtre » — on refusait alors d'arrêter un agent
    qu'on venait de lancer (cause du TimeoutExpired du test ci-dessus sous -n 8)."""
    from bouzecode.web_v2.runtime.runner import agent_processus, agent_vivacite

    lectures = iter([[], [], ["python", "-m", "x", "--session-file", "/s/a.session.json"]])

    class _EnCoursDExec:
        def cmdline(self):
            return next(lectures)

        def status(self):
            return "running"

    monkeypatch.setattr(agent_vivacite.psutil, "Process", lambda pid: _EnCoursDExec())
    agent = Agent(agent_id="neuf01", prompt="p", model="m", cwd="/", pid=4242,
                  started_at="2026-01-01T00:00:00Z", session_path="/s/a.session.json")
    assert agent_processus._pid_still_belongs_to(agent)


def test_refresh_keeps_running_when_ipc_idle(tmp_path, monkeypatch):
    """A live process with IPC status=idle should NOT be terminated."""
    import subprocess, sys

    monkeypatch.setattr("bouzecode.web_v2.runtime.runner.agent_fiche.AGENTS_DIR", tmp_path)

    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(3600)"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )

    ipc_dir = tmp_path / "alive01.ipc"
    ipc_dir.mkdir()
    (ipc_dir / "state.json").write_text(
        json.dumps({"status": "idle", "updated_at": 0}), encoding="utf-8",
    )

    agent = Agent(
        agent_id="alive01", prompt="test", model="m", cwd=str(tmp_path),
        pid=proc.pid, started_at="2026-01-01T00:00:00Z",
        stdout_path=str(tmp_path / "alive01.out.log"),
        session_path=str(tmp_path / "alive01.session.json"),
        ipc_dir=str(ipc_dir),
    )

    result = refresh_agent_status(agent)
    assert result.returncode is None  # still running

    # Cleanup
    proc.terminate()
    proc.wait(timeout=5)
