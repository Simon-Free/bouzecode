# [desc] rehome_agent_cwd : un agent dont le worktree a été nettoyé (ticket mergé) retrouve un
# cwd valide avant respawn — re-provision worktree frais, ou repli repo_root — au lieu de crasher
# (Popen sur dossier disparu → 500 « interromps l'agent »). Vrai git + fakes purs, zéro mock.patch. [/desc]
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from bouzecode.web_v2.runtime import runner
from bouzecode.web_v2.services.work import dispatch, provisioning
from bouzecode.web_v2.services.work import tickets as tickets_svc
from bouzecode.web_v2.services.work import worktrees


def _git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True)


def _make_repo(root: Path) -> Path:
    repo = root / "primary"
    repo.mkdir(parents=True)
    _git(repo, "init", "-q", "-b", "develop")
    (repo / "f.txt").write_text("A\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.email=a@b.c", "-c", "user.name=a", "commit", "-qm", "A")
    return repo


def _agent(tmp_path: Path, cwd: str, *, slug="p", ticket_id="t1") -> runner.Agent:
    return runner.Agent(
        agent_id="rehome001", prompt="x", model="", cwd=cwd, pid=0,
        started_at="", session_path=str(tmp_path / "rehome001.session.json"),
        ticket_slug=slug, ticket_id=ticket_id,
    )


def test_rehome_noop_when_cwd_exists(tmp_path, monkeypatch):
    """cwd toujours présent → aucune re-provision, cwd inchangé."""
    monkeypatch.setattr(runner, "AGENTS_DIR", tmp_path)
    live = tmp_path / "live"
    live.mkdir()
    agent = _agent(tmp_path, str(live))
    assert dispatch.rehome_agent_cwd(agent) == str(live)
    assert agent.cwd == str(live)


def test_rehome_reprovisions_when_cwd_exists_but_not_git(tmp_path, monkeypatch):
    """Piège du dossier fantôme : le cwd EXISTE mais n'est PAS un worktree (readme_sync y a
    repeint un AGENTS.md solitaire, aucun .git). L'ancien no-op os.path.isdir le validait à tort →
    l'agent renaissait sans code. On exige une re-provision (new_cwd ≠ fantôme, contient f.txt)."""
    repo = _make_repo(tmp_path)
    monkeypatch.setattr(worktrees, "WORKTREES_DIR", tmp_path / "wt")
    monkeypatch.setattr(tickets_svc, "TICKETS_DIR", tmp_path / "tickets")
    monkeypatch.setattr(runner, "AGENTS_DIR", tmp_path)
    monkeypatch.setattr(dispatch.projects, "list_projects",
                        lambda: [{"slug": "p", "name": "P", "path": str(repo)}])
    monkeypatch.setattr(provisioning.worktrees, "setup_venv_async", lambda wt, root="", on_result=None: None)
    (tmp_path / "tickets").mkdir()
    (tmp_path / "tickets" / "p.json").write_text(
        json.dumps([{"id": "t1", "runs": [], "worktree": {"state": "cleaned"}}]),
        encoding="utf-8")

    phantom = tmp_path / "phantom"
    phantom.mkdir()
    (phantom / "AGENTS.md").write_text("# solitary\n", encoding="utf-8")  # pas de .git
    agent = _agent(tmp_path, str(phantom))

    new_cwd = dispatch.rehome_agent_cwd(agent)

    assert new_cwd != str(phantom)
    assert Path(new_cwd).is_dir()
    assert (Path(new_cwd) / "f.txt").is_file()
    assert agent.cwd == new_cwd


def test_rehome_reprovisions_fresh_worktree_when_gone(tmp_path, monkeypatch):
    """Worktree disparu + ticket git → re-provision un worktree neuf, cwd pointe vers un dossier
    EXISTANT (≠ l'ancien chemin disparu)."""
    repo = _make_repo(tmp_path)
    monkeypatch.setattr(worktrees, "WORKTREES_DIR", tmp_path / "wt")
    monkeypatch.setattr(tickets_svc, "TICKETS_DIR", tmp_path / "tickets")
    monkeypatch.setattr(runner, "AGENTS_DIR", tmp_path)
    monkeypatch.setattr(dispatch.projects, "list_projects",
                        lambda: [{"slug": "p", "name": "P", "path": str(repo)}])
    monkeypatch.setattr(provisioning.worktrees, "setup_venv_async", lambda wt, root="", on_result=None: None)
    (tmp_path / "tickets").mkdir()
    (tmp_path / "tickets" / "p.json").write_text(
        json.dumps([{"id": "t1", "runs": []}]), encoding="utf-8")

    gone = str(tmp_path / "wt" / "demo-app" / "t1-gone")
    agent = _agent(tmp_path, gone)
    new_cwd = dispatch.rehome_agent_cwd(agent)

    assert new_cwd != gone
    assert Path(new_cwd).is_dir()
    assert agent.cwd == new_cwd
    assert (Path(new_cwd) / "f.txt").is_file()  # descend bien de develop


def test_rehome_falls_back_to_repo_root_when_no_project(tmp_path, monkeypatch):
    """Worktree disparu mais projet introuvable (pas de re-provision possible) → repli sur le
    repo_root enregistré du ticket, s'il existe encore."""
    monkeypatch.setattr(runner, "AGENTS_DIR", tmp_path)
    monkeypatch.setattr(tickets_svc, "TICKETS_DIR", tmp_path / "tickets")
    monkeypatch.setattr(dispatch.projects, "list_projects", lambda: [])
    root = tmp_path / "repo_root"
    root.mkdir()
    (tmp_path / "tickets").mkdir()
    (tmp_path / "tickets" / "p.json").write_text(
        json.dumps([{"id": "t1", "runs": [],
                     "worktree": {"repo_root": str(root)}}]), encoding="utf-8")

    agent = _agent(tmp_path, str(tmp_path / "gone-worktree"))
    assert dispatch.rehome_agent_cwd(agent) == str(root)
    assert agent.cwd == str(root)
