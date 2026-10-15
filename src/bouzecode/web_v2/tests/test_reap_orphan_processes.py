"""Test réel (aucun mock) : reap_session_processes tue le JUMEAU d'un double-spawn — un
vrai process python dont la command line référence le même --session-file, que kill_agent
(un seul pid tracké) ne peut pas atteindre."""
import subprocess
import sys
import time

import psutil

from bouzecode.web_v2.runtime.runner import agent_arret, agent_fiche, agent_processus, agent_respawn


def _visible_with(marker: str) -> bool:
    for proc in psutil.process_iter(["cmdline"]):
        if any(marker in str(a) for a in (proc.info.get("cmdline") or [])):
            return True
    return False


def test_reap_kills_process_on_matching_session_file(tmp_path):
    marker = str(tmp_path / "twin-deadbeef.session.json")
    # Un VRAI process (le « jumeau ») qui porte le marqueur session-file dans sa command line.
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)", marker])
    try:
        deadline = time.time() + 5
        while time.time() < deadline and not _visible_with(marker):
            time.sleep(0.05)
        assert _visible_with(marker), "le process témoin n'est pas visible par psutil"

        killed = agent_arret.reap_session_processes(marker)
        assert killed >= 1

        assert proc.wait(timeout=5) is not None   # il meurt
        assert not _visible_with(marker)
    finally:
        if proc.poll() is None:
            proc.kill()


def test_l_agent_qui_integre_n_est_pas_tue_par_son_propre_reap(tmp_path):
    """L'intégration tourne DANS le process de l'agent : le reap d'après-merge doit tuer le
    jumeau mais épargner l'agent qui l'appelle (sinon SIGTERM en plein appel d'outil)."""
    marker = str(tmp_path / "self-deadbeef.session.json")
    # Jumeau lancé par l'interpréteur de BASE : le python.exe d'un venv uv est un lanceur qui
    # engendre le vrai interpréteur, soit DEUX process marqués. Selon l'ordre des pids et la
    # vitesse du scan, le 2e était déjà mort (tué avec son lanceur) ou pas : « tues 1 » ou
    # « tues 2 » au hasard. Un seul process jumeau garde le compte exact : le jumeau, pas l'agent.
    code = (
        "import subprocess, sys, time\n"
        "from bouzecode.web_v2.runtime.runner import agent_arret, agent_processus\n"
        "python = getattr(sys, '_base_executable', sys.executable)\n"
        f"twin = subprocess.Popen([python, '-c', 'import time; time.sleep(60)', {marker!r}])\n"
        "deadline = time.time() + 5\n"
        f"while time.time() < deadline and not any(p.pid == twin.pid for p in agent_processus._procs_for_session({marker!r})):\n"
        "    time.sleep(0.05)\n"
        f"print('tues', agent_arret.reap_session_processes({marker!r}), flush=True)\n"
        "print('jumeau', twin.wait(timeout=5), flush=True)\n"
        "print('survivant', flush=True)\n"
    )
    agent = subprocess.run([sys.executable, "-c", code, marker], capture_output=True, text=True,
                           timeout=30)
    assert agent.returncode == 0, agent.stderr
    assert "tues 1" in agent.stdout          # le jumeau seul
    assert "survivant" in agent.stdout       # l'agent appelant a survécu à son propre reap
    assert not _visible_with(marker)


def test_reap_noop_on_unknown_or_empty_session(tmp_path):
    assert agent_arret.reap_session_processes(str(tmp_path / "nobody.session.json")) == 0
    assert agent_arret.reap_session_processes("") == 0


def test_session_process_running_detects_live_then_absent(tmp_path):
    marker = str(tmp_path / "live-deadbeef.session.json")
    assert agent_processus._session_process_running(marker) is False
    assert agent_processus._session_process_running("") is False
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)", marker])
    try:
        deadline = time.time() + 5
        while time.time() < deadline and not agent_processus._session_process_running(marker):
            time.sleep(0.05)
        assert agent_processus._session_process_running(marker) is True
    finally:
        if proc.poll() is None:
            proc.kill()


def test_respawn_skips_when_session_process_already_running(tmp_path, monkeypatch):
    """Anti double-spawn : si un process tourne DÉJÀ pour cette session, rien n'est relancé
    et l'appelant l'apprend.

    Le test attendait l'agent en retour. Le produit rend désormais None, et c'est le point :
    un appelant qui reçoit l'agent croit qu'un tour est parti et enregistre un run fantôme,
    alors que rien n'a été lancé (cf. `runner.continue_agent`). Vrai process témoin + Popen
    recorder (pas de mock.patch)."""
    session = str(tmp_path / "twin-cafe.session.json")
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)", session])
    try:
        deadline = time.time() + 5
        while time.time() < deadline and not agent_processus._session_process_running(session):
            time.sleep(0.05)
        assert agent_processus._session_process_running(session)

        popen_calls = []
        monkeypatch.setattr(agent_respawn.subprocess, "Popen",
                            lambda *a, **k: popen_calls.append(a))
        agent = agent_fiche.Agent(agent_id="cafe", prompt="p", model="", cwd=str(tmp_path),
                             pid=0, started_at="t", session_path=session)

        out = agent_respawn._respawn(agent, [], "banner\n")

        assert out is None                # « je n'ai rien relancé » dit à l'appelant
        assert popen_calls == []          # jumeau évité : aucun spawn
        assert agent.pid == 0             # état inchangé (pas de nouveau process)
    finally:
        if proc.poll() is None:
            proc.kill()
