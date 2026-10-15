# [desc] Enfant en fenêtre de terminal : son statut suit son fichier résultat, sa fiche ou sa mort (PID) ; CheckAgentResult attend vraiment et sait l'arrêter ; Fleet/MessageAgent absents hors web. [/desc]
"""Session 9d81964e (2026-10-06) : l'enfant lancé en arrière-plan restait « running » pour
toujours, `CheckAgentResult(wait=true)` rendait la main en 3 s, l'intégration était refusée
sans fin. Les enfants sont ici de VRAIS process Python (le lanceur wt.exe est remplacé)."""
from __future__ import annotations

import re
import subprocess
import sys
import time

import pytest

from bouzecode.backend.multi_agent import terminal as terminal_mod
from bouzecode.backend.multi_agent import gestionnaire, lancement_terminal, outils_enfants
from bouzecode.backend.multi_agent import surveillance_terminal as surveillance_mod
from bouzecode.backend.multi_agent.surveillance_terminal import pid_de_l_enfant
from bouzecode.backend.multi_agent.task import SubAgentTask
from bouzecode.ui.cloture_cli import chemin_fiche

_ENFANT = ("import sys, time; from pathlib import Path; "
           "from bouzecode.backend.multi_agent.surveillance_terminal import ecrire_pid; "
           "ecrire_pid(sys.argv[1]); time.sleep(float(sys.argv[2])); "
           "sys.argv[3] == '1' and Path(sys.argv[1]).write_text('FINI_42', encoding='utf-8')")


def _lanceur(duree_s: float, livre: bool, process: list):
    def lancer(prompt, result_file, config, env_extra=None):
        process.append(subprocess.Popen(
            [sys.executable, "-c", _ENFANT, result_file, str(duree_s), "1" if livre else "0"]))
        return process[-1]
    return lancer


@pytest.fixture
def enfants(monkeypatch):
    process: list = []
    monkeypatch.setattr(lancement_terminal, "_TERMINAL_WAIT_INTERVAL", 0.05)
    yield process, monkeypatch
    for un_process in process:
        un_process.kill()


def _lancer(enfants, duree_s, livre, config):
    process, monkeypatch = enfants
    monkeypatch.setattr(terminal_mod, "spawn_in_terminal", _lanceur(duree_s, livre, process))
    sortie = lancement_terminal._spawn_terminal_agent({"prompt": "x", "background": True}, config)
    return re.search(r"Task ID: (\S+)", sortie).group(1)


def test_wait_bloque_jusqu_au_resultat_d_un_enfant_en_arriere_plan(enfants):
    config = {"_depth": 0}
    task_id = _lancer(enfants, 1.0, True, config)
    sortie = outils_enfants._check_agent_result({"task_id": task_id, "wait": True}, config)
    assert "FINI_42" in sortie
    assert gestionnaire.get_agent_manager().tasks[task_id].status == "completed"


def test_enfant_mort_sans_resultat_passe_en_echec(enfants):
    config = {"_depth": 0}
    task_id = _lancer(enfants, 0.2, False, config)
    tache = gestionnaire.get_agent_manager().wait(task_id, timeout=20)
    assert tache.status == "failed"
    assert "died without a result" in tache.result


def test_un_pid_mort_se_lit_mort_sans_lever():
    """Course vue 1 fois sur 3 : `pid_exists` vrai, l'enfant meurt, `status()` levait
    NoSuchProcess dans le thread de suivi, qui mourait — la tâche restait « running »."""
    enfant = subprocess.Popen([sys.executable, "-c", "pass"])
    enfant.wait(timeout=10)
    pid_mort = enfant.pid
    del enfant  # libère le handle : le PID n'existe plus pour Windows
    assert surveillance_mod._process_vivant(pid_mort) is None


def test_un_suivi_qui_plante_rend_la_tache_en_echec(tmp_path):
    """Le suivi ne doit jamais laisser une tâche « running » sans personne pour la faire
    avancer : ici une fiche de clôture illisible fait lever le relevé."""
    result_file = tmp_path / "enfant.result.txt"
    chemin_fiche(str(result_file)).write_text("{pas du json", encoding="utf-8")
    tache = SubAgentTask(id="suivi-plante", prompt="x", status="running")
    surveillance_mod.surveiller(tache, str(result_file), intervalle_s=0.05).result(timeout=10)
    assert tache.status == "failed" and "follow-up crashed" in tache.result


def test_arreter_tue_le_process_de_l_enfant(enfants):
    config = {"_depth": 0}
    task_id = _lancer(enfants, 60, True, config)
    tache = gestionnaire.get_agent_manager().tasks[task_id]
    debut = time.monotonic()
    while pid_de_l_enfant(tache.result_file) is None:
        assert time.monotonic() - debut < 20, "l'enfant n'a jamais écrit son PID"
        time.sleep(0.05)
    sortie = outils_enfants._check_agent_result({"task_id": task_id, "arreter": True}, config)
    assert "arrêté" in sortie
    assert enfants[0][0].wait(timeout=10) is not None
    assert tache.status == "cancelled"


def test_lancement_rate_sans_pid_echoue_vite(enfants):
    process, monkeypatch = enfants
    monkeypatch.setattr(lancement_terminal, "_TERMINAL_SIGNE_DE_VIE_S", 0.3)
    monkeypatch.setattr(terminal_mod, "spawn_in_terminal", lambda *a, **k: None)
    sortie = lancement_terminal._spawn_terminal_agent({"prompt": "x", "background": True}, {"_depth": 0})
    tache = gestionnaire.get_agent_manager().wait(re.search(r"Task ID: (\S+)", sortie).group(1),
                                               timeout=10)
    assert tache.status == "failed" and "No sign of life" in tache.result


def test_agent_en_pause_ne_declare_pas_mort_un_enfant_encore_vivant(enfants):
    _, monkeypatch = enfants
    monkeypatch.setattr(lancement_terminal, "_TERMINAL_WAIT_TIMEOUT", 0.3)
    process, _ = enfants
    monkeypatch.setattr(terminal_mod, "spawn_in_terminal", _lanceur(30, True, process))
    sortie = lancement_terminal._spawn_terminal_agent({"prompt": "x", "wait": True}, {"_depth": 0})
    assert "Toujours actif" in sortie


def test_fleet_et_message_agent_ne_sont_proposes_qu_en_web(monkeypatch, tmp_path):
    from bouzecode.backend.core.tool_registry import get_tool_schemas
    monkeypatch.delenv("BOUZECODE_WEB_IPC_DIR", raising=False)
    hors_web = {s["name"] for s in get_tool_schemas()}
    assert not {"Fleet", "MessageAgent"} & hors_web
    assert "CheckAgentResult" in hors_web
    monkeypatch.setenv("BOUZECODE_WEB_IPC_DIR", str(tmp_path))
    assert {"Fleet", "MessageAgent"} <= {s["name"] for s in get_tool_schemas()}
