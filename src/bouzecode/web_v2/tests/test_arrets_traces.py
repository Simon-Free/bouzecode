# [desc] Tout arrêt d'agent laisse une ligne au journal (kill, cancel doux), et une reprise est retrouvable depuis l'ancienne fiche. [/desc]
"""Traçabilité des arrêts et des reprises.

* Le journal des arrêts (`kill_journal`) reçoit CHAQUE geste, quel que soit l'appelant — même
  sous pytest, où la terminaison elle-même est inerte (`runner.destruction_permitted`).
* `resume_agent` relance sous un NOUVEL identifiant : l'ancienne fiche garde le pid mort de
  l'ancien process, et un observateur qui la suivait déclarait morte une reprise vivante. Elle
  porte désormais `reprise_par`.
"""
from __future__ import annotations

import json
import sys

import psutil

from bouzecode.web_v2.runtime import kill_journal
from bouzecode.web_v2.runtime.runner import agent_arret, agent_commande, agent_creation, agent_fiche


def _fiche(agent_id: str, **champs) -> agent_fiche.Agent:
    parc = agent_fiche.AGENTS_DIR
    (parc / f"{agent_id}.ipc").mkdir(exist_ok=True)
    donnees = {"agent_id": agent_id, "prompt": "analyse", "model": "m", "cwd": "",
               "pid": 0, "started_at": "2026-09-29T08:12:34Z", "returncode": -1,
               "finished_at": "2026-09-29T08:13:42Z", "ipc_dir": str(parc / f"{agent_id}.ipc"),
               "session_path": str(parc / f"{agent_id}.session.json"),
               "stdout_path": str(parc / f"{agent_id}.out.log"), **champs}
    (parc / f"{agent_id}.json").write_text(json.dumps(donnees), encoding="utf-8")
    return agent_fiche.load_agent(agent_id)


def test_un_kill_et_un_cancel_doux_sont_journalises():
    agent = _fiche("eeee00000005")
    agent_arret.graceful_cancel_agent(agent)
    issue = agent_arret.kill_agent(agent)
    doux, kill = kill_journal.lire()
    assert doux["geste"] == "cancel_doux" and doux["agent_id"] == "eeee00000005"
    assert kill["geste"] == "kill" and kill["signalled"] is issue["signalled"] is False
    assert kill["appelants"][0].endswith("test_arrets_traces.py:"
                                         "test_un_kill_et_un_cancel_doux_sont_journalises")
    assert kill["returncode"] == -1 and kill["serveur_pid"] > 0


def test_l_ancienne_fiche_designe_sa_reprise(monkeypatch):
    """Le programme lancé est remplacé par un `sleep` : on vérifie les fiches, pas le LLM."""
    monkeypatch.setattr(agent_commande, "_agent_cmd",
                        lambda: [sys.executable, "-c", "import time; time.sleep(30)"])
    ancien = _fiche("ffff00000006", pid=4242)
    nouveau = agent_creation.resume_agent(ancien, "Reprends la tâche interrompue.")
    try:
        assert agent_fiche.load_agent("ffff00000006").reprise_par == nouveau.agent_id
        assert agent_fiche.load_agent(nouveau.agent_id).reprise_de == "ffff00000006"
        assert agent_fiche.load_agent(nouveau.agent_id).pid == nouveau.pid != 4242
    finally:
        proc = psutil.Process(nouveau.pid)
        for enfant in proc.children(recursive=True):
            enfant.kill()
        proc.kill()
        proc.wait(timeout=5)
