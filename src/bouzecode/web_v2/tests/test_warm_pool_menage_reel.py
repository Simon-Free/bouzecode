# [desc] Ménage du pool chaud sur de VRAIS process : qui est évincé, qui ne l'est pas, et la trace laissée dans le journal des arrêts. [/desc]
"""`warm_pool.sweep_warm_pool` joué pour de vrai (destruction levée explicitement), sur un parc
isolé et des process fabriqués par le test : `python -c sleep <session_path>`, dont la ligne de
commande référence la session comme celle d'un vrai agent.

Chaque cas est un incident du 2026-09-29 (cf. `warm_pool`, `warmpool`, `kill_journal`).
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone

import psutil
import pytest

from bouzecode.web_v2.runtime import kill_journal
from bouzecode.web_v2.runtime.runner import agent_commande, agent_fiche, agent_vivacite
from bouzecode.web_v2.services.work import _persistence, warm_pool
from bouzecode.web_v2.tests.production_isolation import autoriser_la_destruction

MAINTENANT = datetime.now(timezone.utc)


@pytest.fixture()
def process(request):
    """Fabrique un process vivant ; `avec_session` le fait passer pour celui de l'agent."""
    lances: list[subprocess.Popen] = []

    def lancer(session_path=None) -> psutil.Process:
        args = [sys.executable, "-c", "import time; time.sleep(60)"]
        proc = subprocess.Popen(args + ([str(session_path)] if session_path else []))
        lances.append(proc)
        return psutil.Process(proc.pid)

    yield lancer
    for proc in lances:
        if proc.poll() is None:  # le lanceur du venv relance l'interpréteur comme ENFANT
            for enfant in psutil.Process(proc.pid).children(recursive=True):
                enfant.kill()
            proc.kill()
        proc.wait(timeout=5)


def _utc(minutes: float) -> str:
    return (MAINTENANT - timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _fiche(agent_id, proc, *, avec_identite=True, depuis_min=47.0, sauve_il_y_a_min=20.0,
           returncode=None, finished_at="", close_reason="final_answer", ticket_id=""):
    """Fiche + session + IPC `idle`, comme le runner et le harnais les écrivent."""
    parc = agent_fiche.AGENTS_DIR
    session = parc / f"{agent_id}.session.json"
    sauvegarde = datetime.now() - timedelta(minutes=sauve_il_y_a_min)  # heure LOCALE naïve
    session.write_text(json.dumps({
        "messages": [{"role": "user", "content": "analyse des connexions"}],
        "close_reason": close_reason, "saved_at": sauvegarde.strftime("%Y-%m-%d %H:%M:%S"),
    }), encoding="utf-8")
    ipc_dir = parc / f"{agent_id}.ipc"
    ipc_dir.mkdir()
    (ipc_dir / "state.json").write_text(json.dumps({
        "status": "idle", "turn": 2, "updated_at": sauvegarde.timestamp()}), encoding="utf-8")
    (parc / f"{agent_id}.json").write_text(json.dumps({
        "agent_id": agent_id, "prompt": "analyse des connexions", "model": "m", "cwd": "",
        "pid": proc.pid, "pid_create_time": proc.create_time() if avec_identite else 0.0,
        "started_at": _utc(depuis_min), "finished_at": finished_at, "returncode": returncode,
        "session_path": str(session), "stdout_path": str(parc / f"{agent_id}.out.log"),
        "ipc_dir": str(ipc_dir), "parent": agent_commande.MANUAL_PARENT,
        "ticket_slug": "proj" if ticket_id else "", "ticket_id": ticket_id,
    }), encoding="utf-8")
    return ipc_dir / "cancel.flag"


@pytest.fixture()
def destruction(monkeypatch):
    autoriser_la_destruction(monkeypatch)


def _session_de(agent_id):
    return agent_fiche.AGENTS_DIR / f"{agent_id}.session.json"


def test_conversation_ancienne_dont_le_tour_vient_de_finir_reste_chaude(destruction, process):
    """c4e9964adb48 : lancée il y a 47 min, tour sauvegardé il y a 30 s → gardée."""
    proc = process(_session_de("c4e9964adb48"))
    drapeau = _fiche("c4e9964adb48", proc, sauve_il_y_a_min=0.5)
    assert warm_pool.sweep_warm_pool() == []
    assert proc.is_running() and not drapeau.exists()
    assert kill_journal.lire() == []


def test_eviction_legitime_journalisee_avec_regle_dates_et_pid_verifie(destruction, process):
    proc = process(_session_de("aaaa00000001"))
    drapeau = _fiche("aaaa00000001", proc, sauve_il_y_a_min=20)
    assert warm_pool.sweep_warm_pool() == ["aaaa00000001"]
    proc.wait(timeout=10)
    assert drapeau.exists()
    eviction, kill = kill_journal.lire()
    assert eviction["geste"] == "eviction" and eviction["pid_verifie"] is True
    assert eviction["motif"]["regle"] == "ttl_inactivite"
    assert 1150 < eviction["motif"]["age_s"] < 1300 and eviction["motif"]["ttl_s"] == 900
    assert eviction["pid"] == proc.pid and "warm_pool.py:sweep_warm_pool" in eviction["appelants"][0]
    assert kill["geste"] == "kill" and kill["signalled"] is True and kill["cancel_ecrit"] is True


def test_agent_mort_au_pid_recycle_n_est_ni_tue_ni_marque(destruction, process):
    """13bd7991ec23 : fini le 25/07, fiche sans `pid_create_time`, pid réattribué depuis."""
    proc = process(_session_de("13bd7991ec23"))
    drapeau = _fiche("13bd7991ec23", proc, avec_identite=False, returncode=0,
                     finished_at="2026-07-25T13:06:00.464894Z", depuis_min=90000)
    assert "né après la fin" in agent_vivacite.processus_absent(agent_fiche.load_agent("13bd7991ec23"))
    assert warm_pool.sweep_warm_pool() == []
    assert proc.is_running() and not drapeau.exists()
    assert kill_journal.lire() == []


def test_pid_dont_l_identite_n_est_pas_prouvee_n_est_pas_compte_chaud(destruction, process):
    """Le pid vit et son instant concorde, mais sa ligne de commande n'est pas celle de l'agent."""
    proc = process()  # sans la session dans la ligne de commande
    drapeau = _fiche("bbbb00000002", proc, sauve_il_y_a_min=20)
    assert warm_pool.sweep_warm_pool() == []
    assert proc.is_running() and not drapeau.exists()


def test_agent_avec_travail_en_cours_garde_son_process(destruction, process):
    """4a2d4a23acb3 : ticket ouvert, tour clos sur un refus du modèle → pas d'éviction."""
    _persistence._save("proj", [{"id": "T1", "title": "t", "prompt": "p", "parent": "",
                                 "comments": [], "runs": []}])
    proc = process(_session_de("4a2d4a23acb3"))
    drapeau = _fiche("4a2d4a23acb3", proc, sauve_il_y_a_min=20, close_reason="content_refusal",
                     ticket_id="T1")
    assert warm_pool.sweep_warm_pool() == []
    assert proc.is_running() and not drapeau.exists()


def test_message_non_lu_refus_journalise(destruction, process):
    proc = process(_session_de("cccc00000003"))
    drapeau = _fiche("cccc00000003", proc, sauve_il_y_a_min=20)
    (drapeau.parent / "followup.txt").write_text("une précision", encoding="utf-8")
    assert warm_pool.sweep_warm_pool() == []
    assert proc.is_running() and not drapeau.exists()
    [refus] = kill_journal.lire()
    assert refus["geste"] == "eviction_refusee" and refus["raison"] == "message_non_lu"


def test_hors_du_serveur_de_reference_le_menage_ne_tue_rien(destruction, process, monkeypatch):
    """Un `create_app()` lancé par un script d'agent (smoke sur le port 5099) ne balaie pas."""
    monkeypatch.setattr(warm_pool, "SERVEUR_PRINCIPAL", False)
    proc = process(_session_de("dddd00000004"))
    drapeau = _fiche("dddd00000004", proc, sauve_il_y_a_min=20)
    assert warm_pool.sweep_warm_pool() == []
    assert proc.is_running() and not drapeau.exists()
