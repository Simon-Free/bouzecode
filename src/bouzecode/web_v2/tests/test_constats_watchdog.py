# [desc] Le watchdog CONSTATE (L2) : mort d'un agent debouncée puis `stopped{crashed}`, fin rendue pendant un redémarrage → `delivered`, aucun WIP commité d'office ; le merge, demandé, pose un vrai commit et clôt le ticket. [/desc]
"""Remplace l'ancien `test_workflow.py` (la machine `workflow` a disparu au lot L2) : ce qui est
observé devient une transition de `ticket_fsm`, rien de plus. Vrai store, vraies fiches
d'agent, vrai git sur un dépôt temporaire ; aucun mock."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

import psutil
import pytest

from bouzecode.web_v2.runtime.runner import agent_fiche, agent_registre
from bouzecode.web_v2.services.sessions import store
from bouzecode.web_v2.services.work import constats, integration, projects, tickets, wake, worktrees
from bouzecode.web_v2.services.work.fsm import etats

SLUG = "proj"


@pytest.fixture(autouse=True)
def projet(tmp_path, monkeypatch):
    chemin = tmp_path / "projects.json"
    monkeypatch.setattr(projects, "PROJECTS_PATH", chemin)
    chemin.write_text(json.dumps([{"slug": SLUG, "name": SLUG, "path": str(tmp_path)}]),
                      encoding="utf-8")


def _fiche(agent_id: str, ticket_id: str, close_reason: str | None = None, pid=None) -> None:
    parc = agent_fiche.AGENTS_DIR
    session = parc / f"{agent_id}.session.json"
    (parc / f"{agent_id}.json").write_text(json.dumps({
        "agent_id": agent_id, "prompt": "Corrige", "model": "m", "cwd": "", "pid": pid,
        "pid_create_time": psutil.Process(pid).create_time() if pid else None,
        "started_at": "2026-10-01T10:00:00", "returncode": None if pid else -1,
        "finished_at": "", "session_path": str(session), "ipc_dir": "",
        "stdout_path": str(parc / f"{agent_id}.out.log"), "parent": "",
        "ticket_slug": SLUG, "ticket_id": ticket_id}), encoding="utf-8")
    if close_reason is not None:
        session.write_text(json.dumps({"messages": [], "close_reason": close_reason}),
                           encoding="utf-8")
    agent_fiche._list_agents_cache.clear()
    agent_registre._agent_file_cache.clear()
    store.invalidate_status(agent_id)


def _en_cours(agent_id: str = "dead", **champs) -> dict:
    ticket = tickets.create_ticket(SLUG, "T", "faire")
    if champs:
        tickets.poser(SLUG, ticket, **champs)
    tickets.set_launching(SLUG, ticket)
    tickets.add_run(SLUG, ticket, agent_id, "work", "m")
    return ticket


def _frais(ticket: dict) -> dict:
    return tickets.get_ticket(SLUG, ticket["id"])


def test_une_disparition_fugace_n_est_pas_un_plantage():
    ticket = _en_cours()
    _fiche("dead", ticket["id"])
    wake.tick()
    frais = _frais(ticket)
    assert frais["state"] == etats.RUNNING
    assert frais["runs"][0]["dead_ticks"] == 1


def test_une_mort_confirmee_est_un_arret_et_le_worktree_reste():
    ticket = _en_cours()
    _fiche("dead", ticket["id"])
    for _ in range(constats.MORTS_AVANT_CRASH):
        wake.tick()
    frais = _frais(ticket)
    assert (frais["state"], frais["state_reason"]["code"]) == (etats.STOPPED, "crashed")
    assert frais["runs"][0]["state"] == "ended"


def test_un_agent_revu_vivant_remet_le_compteur_a_zero():
    ticket = _en_cours()
    _fiche("dead", ticket["id"])
    wake.tick()
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        _fiche("dead", ticket["id"], pid=proc.pid)
        wake.tick()
        frais = _frais(ticket)
        assert frais["runs"][0]["dead_ticks"] == 0 and frais["state"] == etats.RUNNING
    finally:
        proc.kill()
        proc.wait(timeout=10)


def test_une_fin_rendue_pendant_un_redemarrage_est_une_livraison():
    """Le hook `/completed` a été perdu, la session dit `final_answer` : livré, pas planté."""
    ticket = _en_cours()
    _fiche("dead", ticket["id"], close_reason="final_answer")
    for _ in range(constats.MORTS_AVANT_CRASH):
        wake.tick()
    frais = _frais(ticket)
    assert frais["state"] == etats.DELIVERED
    assert frais["runs"][0]["completed"] is True and frais["runs"][0]["turns"] == 1


def test_un_agent_mort_sans_rien_rendre_reste_un_plantage():
    ticket = _en_cours()
    _fiche("dead", ticket["id"], close_reason="")
    for _ in range(constats.MORTS_AVANT_CRASH + 1):
        wake.tick()
    frais = _frais(ticket)
    assert frais["state"] == etats.STOPPED and not frais["runs"][0].get("completed")


def _git(repo: Path, *args: str) -> str:
    res = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)
    assert res.returncode == 0, res.stderr
    return res.stdout.strip()


@pytest.fixture()
def develop_repo(tmp_path: Path) -> Path:
    name = f"wfrepo_{uuid.uuid4().hex[:8]}"  # WORKTREES_DIR est rangé par NOM de dépôt
    shutil.rmtree(worktrees.WORKTREES_DIR / name, ignore_errors=True)
    repo = tmp_path / name
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t.t")
    _git(repo, "config", "user.name", "t")
    (repo / "README.md").write_text("init\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")
    _git(repo, "branch", "-M", "main")
    _git(repo, "branch", "develop")
    return repo


def _bac_a_sable(repo: Path, ticket_id: str, fichier: str) -> dict:
    from bouzecode.web_v2.services.work.provisioning import meta_du_worktree
    meta = worktrees.provision(str(repo), ticket_id, base_branch="develop", with_venv=False)
    assert meta["ok"]
    (Path(meta["worktree"]) / fichier).write_text("x = 1\n", encoding="utf-8")
    return meta_du_worktree(meta)


def test_un_plantage_ne_commite_jamais_le_wip(develop_repo: Path):
    ticket = _en_cours()
    meta = _bac_a_sable(develop_repo, ticket["id"], "wip.py")
    tickets.poser(SLUG, ticket, worktree=meta)
    avant = int(_git(develop_repo, "rev-list", "--count", meta["branch"]))
    _fiche("dead", ticket["id"])
    for _ in range(constats.MORTS_AVANT_CRASH):
        wake.tick()
    assert _frais(ticket)["state"] == etats.STOPPED
    assert int(_git(develop_repo, "rev-list", "--count", meta["branch"])) == avant
    assert (Path(meta["worktree"]) / "wip.py").is_file()


def test_le_merge_demande_pose_un_vrai_commit_et_clot_le_ticket(develop_repo: Path):
    ticket = _en_cours("coder1")
    tickets.poser(SLUG, ticket, worktree=_bac_a_sable(develop_repo, ticket["id"], "feat.py"))
    constats.fin_de_run(SLUG, ticket["id"], "coder1", "final_answer")
    avant = _git(develop_repo, "rev-parse", "develop")
    resultat = integration.integrate_ticket(SLUG, _frais(ticket))
    assert resultat["ok"] and resultat["state"] == etats.CLOSED
    assert _git(develop_repo, "rev-parse", "develop") != avant
    assert "feat.py" in _git(develop_repo, "ls-tree", "--name-only", "develop")
    frais = _frais(ticket)
    assert (frais["state"], frais["state_reason"]["code"]) == (etats.CLOSED, "integre")
    assert frais["integration"]["merged_at"] and frais["worktree"]["retire_at"]
    assert not Path(frais["worktree"]["worktree"]).exists()
    again = integration.integrate_ticket(SLUG, frais)
    assert again["code"] == "rien_a_integrer"
