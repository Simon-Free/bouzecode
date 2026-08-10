"""Test réel (aucun mock) : reap_session_processes tue le JUMEAU d'un double-spawn — un
vrai process python dont la command line référence le même --session-file, que kill_agent
(un seul pid tracké) ne peut pas atteindre."""
import subprocess
import sys
import time

import psutil

from bouzecode.web_v2.runtime import runner


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

        killed = runner.reap_session_processes(marker)
        assert killed >= 1

        assert proc.wait(timeout=5) is not None   # il meurt
        assert not _visible_with(marker)
    finally:
        if proc.poll() is None:
            proc.kill()


def test_reap_noop_on_unknown_or_empty_session(tmp_path):
    assert runner.reap_session_processes(str(tmp_path / "nobody.session.json")) == 0
    assert runner.reap_session_processes("") == 0


def test_session_process_running_detects_live_then_absent(tmp_path):
    marker = str(tmp_path / "live-deadbeef.session.json")
    assert runner._session_process_running(marker) is False
    assert runner._session_process_running("") is False
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)", marker])
    try:
        deadline = time.time() + 5
        while time.time() < deadline and not runner._session_process_running(marker):
            time.sleep(0.05)
        assert runner._session_process_running(marker) is True
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
        while time.time() < deadline and not runner._session_process_running(session):
            time.sleep(0.05)
        assert runner._session_process_running(session)

        popen_calls = []
        monkeypatch.setattr(runner.subprocess, "Popen",
                            lambda *a, **k: popen_calls.append(a))
        agent = runner.Agent(agent_id="cafe", prompt="p", model="", cwd=str(tmp_path),
                             pid=0, started_at="t", session_path=session)

        out = runner._respawn(agent, [], "banner\n")

        assert out is None                # « je n'ai rien relancé » dit à l'appelant
        assert popen_calls == []          # jumeau évité : aucun spawn
        assert agent.pid == 0             # état inchangé (pas de nouveau process)
    finally:
        if proc.poll() is None:
            proc.kill()
