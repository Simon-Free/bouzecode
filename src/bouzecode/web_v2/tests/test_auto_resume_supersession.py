# [desc] Reprise auto : un run crashé SUPPLANTÉ par une tentative postérieure ne repart jamais. [/desc]
"""Un ticket relancé après un crash ne fait pas repartir son ancien agent.

Un run mort puis SUPPLANTÉ (le ticket a été relancé, un run plus récent a pris la suite)
ne doit jamais être repris au boot : ça ferait naître un SECOND agent dans le worktree
d'un ticket déjà livré, sur une mission déjà accomplie.

VRAI store SQLite (isolé sous tmp par la fixture autouse) et VRAIS enregistrements
d'agent sur disque. Seule la relance est injectée (`resume_fn`) : aucun process lancé.
"""
from __future__ import annotations

import json
import os

import pytest

from bouzecode.web_v2.runtime import runner
from bouzecode.web_v2.services.work import _persistence, auto_resume, tickets


@pytest.fixture()
def agents(tmp_path, monkeypatch):
    """Redirige les enregistrements d'agent vers tmp (les tickets le sont déjà par l'autouse)."""
    agents_dir = tmp_path / "web_agents"
    agents_dir.mkdir()
    monkeypatch.setattr(runner, "AGENTS_DIR", agents_dir)
    runner._list_agents_cache.clear()
    runner._agent_file_cache.clear()
    return agents_dir


def _ecrire_agent(agents_dir, agent_id: str, **champs) -> None:
    base = {"agent_id": agent_id, "prompt": "p", "model": "", "cwd": "", "pid": 0,
            "started_at": "2026-07-27T10:00:00", "session_path": "", "ipc_dir": ""}
    (agents_dir / f"{agent_id}.json").write_text(
        json.dumps({**base, **champs}), encoding="utf-8")


def _agent_mort(agents_dir, agent_id: str) -> None:
    """Process MORT sans aucune clôture propre : ni close_reason, ni FinalAnswer, ni
    verdict — ce que laisse un serveur tué en plein travail."""
    _ecrire_agent(agents_dir, agent_id, returncode=-1)


def _agent_livre(agents_dir, agent_id: str) -> None:
    """Agent terminé PROPREMENT : sorti en 0, session close sur `final_answer` — la preuve
    de livraison que croise `liveness.classify_agent_run`."""
    session = agents_dir / f"{agent_id}.session.json"
    session.write_text(json.dumps(
        {"close_reason": "final_answer", "final_answer": "livré", "messages": []}),
        encoding="utf-8")
    _ecrire_agent(agents_dir, agent_id, returncode=0, session_path=str(session))


def _agent_vivant(agents_dir, agent_id: str) -> None:
    """Process qui TOURNE ENCORE : pas de returncode et un pid réellement vivant (celui du
    process de test), ce que `runner.is_running` vérifie via psutil."""
    _ecrire_agent(agents_dir, agent_id, returncode=None, pid=os.getpid())


def _ticket_avec_runs(runs: list[dict], parent: str = "") -> None:
    """Sème un ticket OUVERT avec les runs donnés. Ordre du store : `add_run` insérant
    chaque run EN TÊTE, runs[0] est le PLUS RÉCENT et runs[-1] le plus ancien."""
    _persistence._save("proj", [{
        "id": "T1", "title": "T", "prompt": "p", "parent": parent,
        "comments": [], "runs": runs,
    }])


def _refuse_toute_reprise(agent_id: str, prompt: str) -> str:
    raise AssertionError(f"reprise INTERDITE, pourtant tentée sur {agent_id}")


def _run_persiste(index: int) -> dict:
    return tickets.get_ticket("proj", "T1")["runs"][index]


def _commentaires() -> list[str]:
    return [c["text"] for c in tickets.get_ticket("proj", "T1")["comments"]]


def _ancien_et_recent(agents_dir, recent_id: str) -> None:
    """Un ticket dispatché par un manager, avec l'ancien run crashé ('sub-1') et un run
    POSTÉRIEUR (`recent_id`) dont l'appelant choisit l'état."""
    _ticket_avec_runs([
        {"agent_id": recent_id, "kind": "work", "verdict": None},  # le plus récent
        {"agent_id": "sub-1", "kind": "work", "verdict": None},    # l'ancien, crashé
    ], parent="mgr-42")
    _agent_mort(agents_dir, "sub-1")


def test_un_run_crashe_supplante_par_un_run_qui_a_livre_n_est_pas_repris(agents):
    """Le cas réel : le ticket a été relancé, la relance a LIVRÉ. L'ancien run crashé est
    refusé, la raison est écrite sur le run et le flag persistant posé."""
    _ancien_et_recent(agents, "relance")
    _agent_livre(agents, "relance")

    attempts = auto_resume.resume_subagents(resume_fn=_refuse_toute_reprise)

    assert [(a["agent_id"], a["ok"]) for a in attempts] == [("sub-1", False)]
    assert "supplanté" in attempts[0]["error"]
    ancien = _run_persiste(1)
    assert "supplanté" in ancien["auto_resume_error"]
    assert ancien["auto_resumed"]  # plus réévalué aux boots suivants
    assert "REFUSÉE" in _commentaires()[0]


def test_un_run_crashe_supplante_par_un_run_encore_vivant_n_est_pas_repris(agents):
    """Même refus quand la tentative postérieure TOURNE ENCORE : on ne double pas un agent
    en vol."""
    _ancien_et_recent(agents, "relance")
    _agent_vivant(agents, "relance")

    attempts = auto_resume.resume_subagents(resume_fn=_refuse_toute_reprise)

    assert [a["ok"] for a in attempts] == [False]
    assert "supplanté" in attempts[0]["error"]


def test_deux_runs_crashes_ne_reprennent_que_le_plus_recent(agents):
    """Deux runs morts sur le même ticket : SEUL le plus récent repart — deux agents
    relancés dans le même worktree se piétineraient."""
    _ancien_et_recent(agents, "recent")
    _agent_mort(agents, "recent")
    repris = []

    def reprend(agent_id: str, prompt: str) -> str:
        repris.append(agent_id)
        return "new-1"

    attempts = auto_resume.resume_subagents(resume_fn=reprend)

    assert repris == ["recent"]
    assert [(a["agent_id"], a["ok"]) for a in attempts] == [("recent", True), ("sub-1", False)]
    assert "supplanté" in _run_persiste(1)["auto_resume_error"]


def test_le_run_le_plus_recent_reste_repris_meme_avec_un_ancien_run_livre(agents):
    """Garde-fou inverse : un run ANTÉRIEUR déjà livré ne bloque pas la reprise du run le
    plus récent, qui est bien la dernière tentative en date."""
    _ticket_avec_runs([
        {"agent_id": "sub-1", "kind": "work", "verdict": None},  # le plus récent : crashé
        {"agent_id": "vieux", "kind": "work", "verdict": None},  # antérieur : a livré
    ], parent="mgr-42")
    _agent_mort(agents, "sub-1")
    _agent_livre(agents, "vieux")

    attempts = auto_resume.resume_subagents(resume_fn=lambda agent_id, prompt: "new-1")

    assert [(a["agent_id"], a["ok"]) for a in attempts] == [("sub-1", True)]
