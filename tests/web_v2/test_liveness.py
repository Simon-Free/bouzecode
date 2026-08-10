"""Tests du classifieur partagé dérivé de PREUVES (liveness).

Chacun des 4 états cibles (running / delivered / crashed / stalled) est reproduit
en fixture minimale, PLUS le cas 5 mesuré : agent mort avec close_reason VIDE et
returncode != -1 (donc invisible à l'ancien test `returncode == -1`) doit être
classé `crashed`. AUCUN mock.patch — on redirige les stores fichier sur tmp_path
et on écrit de vrais fichiers agent + session, exactement comme le boot réel les lit.
"""
import json
import os
from datetime import datetime

import pytest

from bouzecode.web_v2.runtime import runner
from bouzecode.web_v2.services.work import liveness


@pytest.fixture
def stores(tmp_path, monkeypatch):
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    monkeypatch.setattr(runner, "AGENTS_DIR", agents_dir)
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


def test_run_delivered_clean_close_reason(stores):
    """text_no_tools sur un run validate (pas work) = clôture gracieuse → delivered."""
    _write_agent(stores["agents"], "a5", returncode=0)
    _write_session(stores["agents"], "a5", close_reason="text_no_tools")
    run = _run("a5", kind="validate")
    assert liveness.classify_agent_run(_ticket([run]), run) == "delivered"


def test_run_running_pid_alive(stores):
    _write_agent(stores["agents"], "a6", returncode=None, alive=True)
    run = _run("a6")
    assert liveness.classify_agent_run(_ticket([run]), run) == "running"


# --- classify_ticket ------------------------------------------------------

def test_ticket_work_done_sans_issue_terminale_attend_une_decision(stores):
    """Run work fini, aucun validateur, aucun merge → `awaiting_decision`.

    Ce test attendait `stalled`. `stalled` a été RESTREINT depuis (cf. la docstring de
    `classify_ticket`) : il ne désigne plus qu'un ticket dont le travail n'est commité
    NULLE PART, donc réellement en péril. Le mot couvrait aussi la simple attente de
    décision, et le board annonçait « stalled » — lu comme « planté » — pour un ticket
    sain. Depuis le retrait de la chaîne automatique, attendre une décision est l'issue
    NORMALE : c'est ce que ce test tient maintenant."""
    _write_agent(stores["agents"], "b1", returncode=0)
    _write_session(stores["agents"], "b1", close_reason="final_answer",
                   final_answer="rien à faire")
    run = _run("b1", kind="work")
    run["no_diff_notified"] = True
    ticket = _ticket([run])  # pas de worktree.state integrated → terminal_outcome None
    assert liveness.classify_ticket(ticket) == "awaiting_decision"


def test_ticket_stalled_quand_le_travail_n_est_commite_nulle_part(stores, monkeypatch):
    """L'autre moitié du découpage, qui doit rester tenue : un travail livré mais commité
    nulle part est en PÉRIL, pas en attente — c'est le seul cas où `stalled` subsiste."""
    _write_agent(stores["agents"], "b9", returncode=0)
    _write_session(stores["agents"], "b9", close_reason="final_answer",
                   final_answer="fait, mais rien de commité")
    run = _run("b9", kind="work")
    ticket = _ticket([run])
    monkeypatch.setattr(liveness.delivery, "delivery_at_risk", lambda t: True)
    assert liveness.classify_ticket(ticket) == "stalled"


def test_ticket_delivered_integrated(stores):
    _write_agent(stores["agents"], "b2", returncode=0)
    _write_session(stores["agents"], "b2", close_reason="final_answer",
                   final_answer="done")
    run = _run("b2", kind="work", completed=True)
    ticket = _ticket([run], worktree={"state": "integrated"})
    assert liveness.classify_ticket(ticket) == "delivered"


def test_ticket_crashed(stores):
    _write_agent(stores["agents"], "b3", returncode=0)
    _write_session(stores["agents"], "b3", close_reason="", final_answer="")
    run = _run("b3", kind="work")
    assert liveness.classify_ticket(_ticket([run])) == "crashed"


def test_ticket_launching_no_run(stores):
    ticket = _ticket([], launching=True)
    assert liveness.classify_ticket(ticket) == "launching"


def test_ticket_running(stores):
    _write_agent(stores["agents"], "b4", returncode=None, alive=True)
    run = _run("b4")
    assert liveness.classify_ticket(_ticket([run])) == "running"
