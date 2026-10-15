"""Tests du classifieur d'AGENT dérivé de PREUVES (liveness).

L'état d'un TICKET n'est plus classé ici (lot L2 : `ticket.state`, écrit par `ticket_fsm`).
Chaque vivacité d'agent (running / delivered / crashed) est reproduite en fixture minimale,
PLUS le cas 5 mesuré : agent mort avec close_reason VIDE et
returncode != -1 (donc invisible à l'ancien test `returncode == -1`) doit être
classé `crashed`. AUCUN mock.patch — on redirige les stores fichier sur tmp_path
et on écrit de vrais fichiers agent + session, exactement comme le boot réel les lit.
"""
import json
import os
from datetime import datetime

import pytest

from bouzecode.web_v2.runtime.runner import agent_fiche
from bouzecode.web_v2.services.work import liveness


@pytest.fixture
def stores(tmp_path, monkeypatch):
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    monkeypatch.setattr(agent_fiche, "AGENTS_DIR", agents_dir)
    return {"agents": agents_dir}


def _write_agent(agents_dir, agent_id, *, returncode, alive=False, ipc_dir=""):
    """Écrit un fichier agent JSON. pid mort par défaut (999999999)."""
    data = {
        "agent_id": agent_id,
        "prompt": "fais le truc",
        "model": "sonnet",
        "cwd": str(agents_dir),
        "pid": os.getpid() if alive else 999999999,
        "started_at": datetime.utcnow().isoformat() + "Z",
        "returncode": returncode,
        "ipc_dir": ipc_dir,
    }
    (agents_dir / f"{agent_id}.json").write_text(json.dumps(data), encoding="utf-8")


def _write_session(agents_dir, agent_id, *, close_reason="", final_answer=""):
    """Écrit la session disque lue par le classifieur (store.load_session_json)."""
    data = {"close_reason": close_reason, "final_answer": final_answer}
    (agents_dir / f"{agent_id}.session.json").write_text(
        json.dumps(data), encoding="utf-8")


def _run(agent_id, *, kind="work", verdict="", completed=False):
    return {"agent_id": agent_id, "kind": kind, "verdict": verdict,
            "completed": completed}


def _ticket(runs, **overrides):
    t = {"id": "T1", "typology": "feature", "runs": runs}
    t.update(overrides)
    return t


# --- classify_agent_run ---------------------------------------------------

def test_run_delivered_final_answer_empty_close_reason(stores):
    """Cas 1 : agent rc=0, FinalAnswer présent, close_reason VIDE → delivered
    (tolère les sessions historiques dont le close_reason n'a jamais été stampé)."""
    _write_agent(stores["agents"], "a1", returncode=0)
    _write_session(stores["agents"], "a1", close_reason="", final_answer="VERDICT: OK")
    run = _run("a1")
    assert liveness.classify_agent_run(_ticket([run]), run) == "delivered"


def test_run_crashed_empty_close_reason_no_final_answer(stores):
    """Cas 5 : pid mort, close_reason VIDE, PAS de FinalAnswer, rc=0 (≠ -1) →
    crashed. L'ancien classement (returncode == -1) le ratait."""
    _write_agent(stores["agents"], "a2", returncode=0)
    _write_session(stores["agents"], "a2", close_reason="", final_answer="")
    run = _run("a2")
    assert liveness.classify_agent_run(_ticket([run]), run) == "crashed"


def test_run_crashed_api_error(stores):
    _write_agent(stores["agents"], "a3", returncode=1)
    _write_session(stores["agents"], "a3", close_reason="api_error")
    run = _run("a3")
    assert liveness.classify_agent_run(_ticket([run]), run) == "crashed"


def test_run_crashed_work_abandoned_mid_turn(stores):
    """work + text_no_tools = arrêt en plein milieu, pas une complétion → crashed."""
    _write_agent(stores["agents"], "a4", returncode=0)
    _write_session(stores["agents"], "a4", close_reason="text_no_tools")
    run = _run("a4", kind="work")
    assert liveness.classify_agent_run(_ticket([run]), run) == "crashed"


def test_une_fin_sur_de_la_prose_n_est_jamais_une_livraison(stores):
    """text_no_tools, quel que soit le kind (même un run `validate` hérité) : aucune réponse
    finale n'est prouvée — la SEULE table (`close_reasons.issue_de_fin`) le dit non livré."""
    _write_agent(stores["agents"], "a5", returncode=0)
    _write_session(stores["agents"], "a5", close_reason="text_no_tools")
    run = _run("a5", kind="validate")
    assert liveness.classify_agent_run(_ticket([run]), run) == "crashed"


def test_run_running_pid_alive(stores):
    _write_agent(stores["agents"], "a6", returncode=None, alive=True)
    run = _run("a6")
    assert liveness.classify_agent_run(_ticket([run]), run) == "running"


# --- clôture mémorisée par version du fichier de session --------------------

def _compter_lectures(monkeypatch):
    lectures = []
    vraie = liveness.store.load_session_json

    def espion(path):
        lectures.append(str(path))
        return vraie(path)

    monkeypatch.setattr(liveness.store, "load_session_json", espion)
    return lectures


def test_cloture_lue_une_seule_fois_tant_que_la_session_ne_change_pas(stores, monkeypatch):
    """Un agent mort n'écrit plus : sa session n'est décodée qu'UNE fois, quel que soit le
    nombre de classifications (le poll de la navigation en fait une par agent mort)."""
    _write_agent(stores["agents"], "m1", returncode=0)
    _write_session(stores["agents"], "m1", close_reason="", final_answer="VERDICT: OK")
    lectures = _compter_lectures(monkeypatch)
    run = _run("m1")
    verdicts = [liveness.classify_agent_run(_ticket([run]), run) for _ in range(5)]
    assert verdicts == ["delivered"] * 5
    assert len(lectures) == 1


def test_cloture_relue_quand_la_session_change(stores, monkeypatch):
    """La mémoire suit la VERSION du fichier : une session réécrite (clôture différente)
    est relue et le verdict suit, identique à une lecture sans mémoire."""
    _write_agent(stores["agents"], "m2", returncode=0)
    _write_session(stores["agents"], "m2", close_reason="", final_answer="VERDICT: OK")
    run = _run("m2")
    assert liveness.classify_agent_run(_ticket([run]), run) == "delivered"
    chemin = stores["agents"] / "m2.session.json"
    avant = chemin.stat().st_mtime_ns
    _write_session(stores["agents"], "m2", close_reason="api_error")
    os.utime(chemin, ns=(avant + 10**9, avant + 10**9))
    lectures = _compter_lectures(monkeypatch)
    assert liveness.classify_agent_run(_ticket([run]), run) == "crashed"
    assert len(lectures) == 1
