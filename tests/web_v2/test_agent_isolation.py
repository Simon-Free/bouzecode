# [desc] L'isolation demandée au lancement d'un agent : shared / worktree / worktree+venv, et le garde-fou anti-collision. [/desc]
"""Ce que l'utilisateur (ou le manager) obtient selon l'environnement qu'il demande.

Vrai git sur un dépôt temporaire, vrai store de tickets ; on n'espionne que le spawn de
l'agent et la création du venv (un `uv sync` réel prendrait des dizaines de secondes)."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from bouzecode.web_v2.services.work import dispatch, isolation, worktrees
from bouzecode.web_v2.services.work import tickets as tickets_svc


class _SpawnedAgent:
    def __init__(self, agent_id="agent000000"):
        self.agent_id = agent_id


class _Agent:
    """Un agent du parc, tel que `runner.list_agents()` le rend : un cwd et un état."""

    def __init__(self, agent_id: str, cwd: str):
        self.agent_id = agent_id
        self.cwd = cwd


def _git(repo: Path, *args: str) -> None:
    res = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)
    assert res.returncode == 0, res.stderr


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    """Un dépôt git minimal, comme un projet réel ouvert dans l'UI."""
    root = tmp_path / "projet"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@t.t")
    _git(root, "config", "user.name", "t")
    (root / "README.md").write_text("init\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "init")
    return root


@pytest.fixture()
def launched(monkeypatch, tmp_path, repo):
    """Câble un projet unique et enregistre worktrees créés / venvs demandés / cwd du spawn."""
    monkeypatch.setattr(tickets_svc, "TICKETS_DIR", tmp_path / "tickets")
    project = {"slug": "p", "name": "Projet", "path": str(repo)}
    monkeypatch.setattr(dispatch.projects, "list_projects", lambda: [project])
    monkeypatch.setattr(dispatch.projects, "find", lambda slug: project)
    monkeypatch.setattr(dispatch, "get_typology",
                        lambda name, path: {"profile": "", "default_model": ""})
    record: dict[str, list] = {"venv": [], "cwd": []}
    monkeypatch.setattr(worktrees, "setup_venv_async",
                        lambda wt, root, on_result=None: record["venv"].append(wt))

    def _spawn(prompt, model, cwd, **kwargs):
        record["cwd"].append(cwd)
        return _SpawnedAgent()
    monkeypatch.setattr(dispatch.runner, "create_agent", _spawn)
    monkeypatch.setattr(isolation, "agents_sharing_cwd", lambda cwd: [])
    return record


def _dispatch(mode: str) -> dict:
    return dispatch.dispatch("fais un truc", project_slug="p", typology="default",
                             isolation=mode)


# ── ce que chaque valeur provisionne ─────────────────────────────────────────

def test_shared_agent_provisions_nothing(launched, repo):
    """Un agent « shared » lancé seul travaille dans le dépôt, sans worktree ni venv."""
    result = _dispatch("shared")

    assert result["isolation"] == "shared"
    assert launched["cwd"] == [str(repo)]
    assert launched["venv"] == []
    assert "worktree" not in tickets_svc.get_ticket("p", result["ticket_id"])


def test_worktree_agent_gets_a_worktree_but_no_venv(launched, repo):
    """Un agent « worktree » reçoit son propre arbre de travail, mais aucun venv."""
    result = _dispatch("worktree")

    assert result["isolation"] == "worktree"
    assert launched["venv"] == [], "worktree seul ne doit JAMAIS payer un uv sync"
    meta = tickets_svc.get_ticket("p", result["ticket_id"])["worktree"]
    assert meta["ok"] and Path(meta["worktree"]).is_dir()
    assert launched["cwd"] == [meta["worktree"]]


def test_worktree_venv_agent_gets_both(launched):
    """Un agent « worktree+venv » reçoit à la fois son arbre de travail et son venv."""
    result = _dispatch("worktree+venv")

    assert result["isolation"] == "worktree+venv"
    meta = tickets_svc.get_ticket("p", result["ticket_id"])["worktree"]
    assert launched["venv"] == [meta["worktree"]]


# ── le garde-fou : deux « shared » sur le même dépôt ─────────────────────────

def test_second_shared_agent_on_the_same_repo_is_isolated(launched, monkeypatch, repo):
    """Un second agent « shared » sur le même dépôt est isolé d'office, et on le lui dit."""
    monkeypatch.setattr(isolation, "agents_sharing_cwd", lambda cwd: ["premier-agent"])

    result = _dispatch("shared")

    assert result["isolation"] == "worktree"
    ticket = tickets_svc.get_ticket("p", result["ticket_id"])
    assert ticket["worktree"]["ok"]
    comment = ticket["comments"][0]["text"]
    assert "premier-agent" in comment and "worktree" in comment
    assert launched["venv"] == [], "le rattrapage donne un worktree, jamais un venv"


def test_lone_shared_agent_is_left_alone(launched, monkeypatch):
    """Tant que personne d'autre ne travaille dans le dépôt, « shared » reste « shared »."""
    monkeypatch.setattr(isolation, "agents_sharing_cwd", lambda cwd: [])

    result = _dispatch("shared")

    assert result["isolation"] == "shared"
    assert tickets_svc.get_ticket("p", result["ticket_id"]).get("comments") == []


def test_busy_repo_counts_only_agents_still_working(monkeypatch, repo):
    """Seuls les agents ENCORE actifs occupent le dépôt : un agent fini ne bloque personne."""
    from bouzecode.web_v2.runtime import runner
    from bouzecode.web_v2.services.sessions import store
    agents = [_Agent("actif", str(repo)), _Agent("fini", str(repo)),
              _Agent("ailleurs", str(repo / "autre"))]
    states = {"actif": "running", "fini": "finished", "ailleurs": "running"}
    monkeypatch.setattr(runner, "list_agents", lambda: agents)
    monkeypatch.setattr(store, "agent_status", lambda a: {"state": states[a.agent_id]})

    assert isolation.agents_sharing_cwd(str(repo)) == ["actif"]


# ── normalisation de la valeur ───────────────────────────────────────────────

def test_unknown_isolation_value_falls_back_to_shared(monkeypatch, repo):
    """Une valeur d'isolation inconnue retombe sur le défaut le moins cher."""
    monkeypatch.setattr(isolation, "agents_sharing_cwd", lambda cwd: [])
    mode, _reason, note = isolation.resolve_isolation(str(repo), "n'importe quoi")
    assert mode == "shared" and note == ""


def test_non_git_project_can_never_be_isolated(tmp_path):
    """Sur un projet qui n'est pas sous git, aucun worktree n'est possible."""
    plain = tmp_path / "pas-un-depot"
    plain.mkdir()
    mode, reason, _note = isolation.resolve_isolation(str(plain), "worktree+venv")
    assert mode == "shared" and "git" in reason


def test_resume_needs_a_worktree_even_when_shared_is_asked(monkeypatch, repo):
    """Reprendre une branche existante exige un arbre dédié, quoi qu'on ait demandé."""
    monkeypatch.setattr(isolation, "agents_sharing_cwd", lambda cwd: [])
    mode, _reason, _note = isolation.resolve_isolation(str(repo), "shared", needs_worktree=True)
    assert mode == "worktree"
