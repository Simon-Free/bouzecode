# [desc] Décor commun aux tests de livraison : dépôt git réel, worktree d'agent, ticket livré. [/desc]
"""Fixtures partagées par `test_delivery_harvest.py` et `test_delivery_views_agree.py`.

Aucun mock : un vrai dépôt git avec `develop` NON checkout (comme en prod, où le
serveur tient l'arbre principal), un vrai `git worktree`, le vrai store SQLite et de
vrais fichiers d'agent. Ce module n'est PAS collecté par pytest (pas de préfixe
`test_`) : il n'expose que des fixtures et des constructeurs d'état."""
from __future__ import annotations

import json
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

from bouzecode.web_v2.runtime import runner
from bouzecode.web_v2.services.sessions import store
from bouzecode.web_v2.services.work import fleet, projects, worktrees
from bouzecode.web_v2.services.work import tickets as tickets_svc

SLUG = "demo-app"
CODEUR = "c12bf30ad26b"
PID_INEXISTANT = 4_000_000


def git_out(cwd: Path | str, *args: str) -> str:
    res = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True,
                         text=True, encoding="utf-8", errors="replace")
    return res.stdout.strip()


@pytest.fixture()
def develop_repo(tmp_path: Path) -> Path:
    """Dépôt dont `develop` existe mais n'est PAS checkout (main l'est)."""
    name = f"delrepo_{uuid.uuid4().hex[:8]}"  # WORKTREES_DIR est indexé par NOM de dépôt
    shutil.rmtree(worktrees.WORKTREES_DIR / name, ignore_errors=True)
    repo = tmp_path / name
    repo.mkdir()
    git_out(repo, "init", "-q")
    git_out(repo, "config", "user.email", "t@t.t")
    git_out(repo, "config", "user.name", "t")
    (repo / "README.md").write_text("init\n", encoding="utf-8")
    git_out(repo, "add", "-A")
    git_out(repo, "commit", "-q", "-m", "init")
    git_out(repo, "branch", "-M", "main")
    git_out(repo, "branch", "develop")
    return repo


@pytest.fixture()
def agents_dir(tmp_path, monkeypatch) -> Path:
    directory = tmp_path / "agents"
    directory.mkdir()
    monkeypatch.setattr(runner, "AGENTS_DIR", directory)
    monkeypatch.setattr(fleet, "sweep_warm_pool", lambda: [])
    # Le cache d'arbre est un global de module qui SERT LA VERSION CONNUE pendant qu'il
    # recalcule (cf. fleet_cache) : sans cette ardoise propre, un test hériterait de l'arbre
    # du parc d'agents du test précédent. Même précaution que la fixture de
    # test_agents_tree_api.py.
    fleet.clear_tree_cache()
    return directory


@pytest.fixture()
def project(develop_repo, tmp_path, monkeypatch) -> Path:
    """Enregistre le dépôt comme projet du serveur (les routes en dépendent)."""
    path = tmp_path / "projects.json"
    path.write_text(json.dumps(
        [{"slug": SLUG, "name": "Demo App", "path": str(develop_repo)}]), encoding="utf-8")
    monkeypatch.setattr(projects, "PROJECTS_PATH", path)
    return develop_repo


@pytest.fixture()
def client(monkeypatch):
    from bouzecode.web_v2.app import create_app
    monkeypatch.setenv("BOUZECODE_WAKE_POLLER", "0")  # thread qui survivrait au test
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as flask_client:
        yield flask_client


def delivered_ticket(repo: Path, titre: str, produced: str = "fix.py") -> dict:
    """Ticket dont l'unique run `work` a fini PROPREMENT (`completed`) en laissant du
    travail NON COMMITÉ dans son worktree — l'état exact des cas vécus a88aeb4c/e03adb3b."""
    ticket = tickets_svc.create_ticket(SLUG, titre, "corrige la faille")
    meta = worktrees.provision(str(repo), ticket["id"], base_branch="develop", with_venv=False)
    assert meta["ok"], meta
    (Path(meta["worktree"]) / produced).write_text("x = 1\n", encoding="utf-8")
    tickets_svc.add_run(SLUG, ticket, CODEUR, "work", "", typology="coder")
    ticket["worktree"] = meta
    ticket["typology"] = "coder"
    tickets_svc.update_ticket(SLUG, ticket)
    tickets_svc.mark_run_completed(SLUG, ticket, CODEUR)
    return tickets_svc.get_ticket(SLUG, ticket["id"])


def finished_agent(agents_dir: Path, cwd: str) -> None:
    """Fichier agent RÉEL d'un codeur qui a clos proprement : pid mort, rc=0, final_answer."""
    session = agents_dir / f"{CODEUR}.session.json"
    (agents_dir / f"{CODEUR}.json").write_text(json.dumps({
        "agent_id": CODEUR, "prompt": "corrige la faille", "model": "opus", "cwd": cwd,
        "pid": PID_INEXISTANT, "returncode": 0, "run_kind": "work",
        "started_at": "2026-07-28T11:08:14", "session_path": str(session),
    }), encoding="utf-8")
    session.write_text(json.dumps({
        "messages": [{"role": "assistant", "content": "fait"}],
        "close_reason": "final_answer", "final_answer": "faille cloisonnée",
    }), encoding="utf-8")
    store.invalidate_status(CODEUR)
    # `list_agents` est caché 3 s : sans ce vidage, l'agent qu'on vient d'écrire reste
    # INVISIBLE si le cache a été peuplé (vide) moins de 3 s plus tôt — par le boot de
    # l'application ou par le tick du watchdog. Le test réussissait ou échouait selon la
    # chance : à HEAD il passe dans la suite complète et échoue lancé seul. Une fausse
    # régression prête à accuser le prochain changement de code.
    runner._list_agents_cache.clear()


def block_git_index(worktree: str) -> Path:
    """Pose le verrou d'index git du worktree : tout `git add` y échoue, exactement comme
    lors d'une opération git concurrente. Cause RÉELLE d'un harvest qui n'aboutit pas."""
    lock = Path(git_out(worktree, "rev-parse", "--absolute-git-dir")) / "index.lock"
    lock.write_text("", encoding="utf-8")
    return lock
