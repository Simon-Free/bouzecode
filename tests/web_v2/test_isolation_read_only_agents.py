# [desc] Le garde-fou anti-collision ne compte que les agents CAPABLES D'ÉCRIRE. [/desc]
"""Qui « occupe » vraiment le dépôt principal ? Seulement ceux qui peuvent y écrire.

Un manager est read-only par construction : son profil ne lui accorde ni `Write`, ni
`Edit`, ni `Bash` (ses appels reviennent « tool is currently disabled »). Il ne peut donc
écraser le travail de personne, et ne doit jamais forcer un worktree à l'enfant qu'il
dispatche — sinon un agent d'inventaire rend des chemins absolus vers un worktree jetable.

Les profils employés ici sont les VRAIS profils builtin : c'est bien la whitelist `tools:`
réellement accordée qui décide, pas le nom de la typologie."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from bouzecode.web_v2.runtime import runner
from bouzecode.web_v2.services.sessions import store
from bouzecode.web_v2.services.work import isolation


class _Agent:
    """Un agent du parc, tel que `runner.list_agents()` le rend : un cwd et un profil."""

    def __init__(self, agent_id: str, cwd: str, profile: str):
        self.agent_id = agent_id
        self.cwd = cwd
        self.profile = profile


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    """Un dépôt git minimal, comme un projet réel ouvert dans l'UI."""
    root = tmp_path / "projet"
    root.mkdir()
    for args in (("init", "-q"), ("config", "user.email", "t@t.t"), ("config", "user.name", "t")):
        assert subprocess.run(["git", *args], cwd=root, capture_output=True).returncode == 0
    return root


@pytest.fixture()
def parc(monkeypatch):
    """Peuple le parc d'agents : tous « running », tous dans le dépôt passé en argument."""

    def _install(cwd: Path, *profiles: tuple[str, str]) -> None:
        agents = [_Agent(agent_id, str(cwd), profile) for agent_id, profile in profiles]
        monkeypatch.setattr(runner, "list_agents", lambda: agents)
        monkeypatch.setattr(store, "agent_status", lambda a: {"state": "running"})

    return _install


# ── le bug du jour : un manager read-only n'occupe pas le dépôt ──────────────

def test_a_read_only_manager_leaves_the_repo_free(parc, repo):
    """Un manager actif dans le dépôt ne l'occupe pas : il ne peut rien y écrire."""
    parc(repo, ("9d0789f2fdca", "manager"))

    assert isolation.agents_sharing_cwd(str(repo)) == []


def test_a_child_asking_shared_under_a_manager_stays_shared(parc, repo):
    """L'enfant qu'un manager `shared` dispatche en `shared` RESTE dans le dépôt principal."""
    parc(repo, ("9d0789f2fdca", "manager"))

    mode, _reason, comment = isolation.resolve_isolation(str(repo), "shared")

    assert mode == "shared", "le manager read-only ne doit plus déclencher le garde-fou"
    assert comment == ""


# ── le garde-fou reste entier pour les vrais écrivains ──────────────────────

def test_an_active_coder_still_forces_a_worktree(parc, repo):
    """Un codeur déjà à l'œuvre dans le dépôt isole toujours d'office le suivant."""
    parc(repo, ("codeur-en-place", "coder"))

    mode, reason, comment = isolation.resolve_isolation(str(repo), "shared")

    assert mode == "worktree"
    assert "codeur-en-place" in comment and "worktree" in comment
    assert "1 agent" in reason


def test_an_agent_without_a_profile_counts_as_a_writer(parc, repo):
    """Sans whitelist d'outils, un agent garde Write/Edit/Bash : il occupe le dépôt."""
    parc(repo, ("agent-nu", ""))

    assert isolation.agents_sharing_cwd(str(repo)) == ["agent-nu"]


def test_only_the_writer_is_named_when_a_manager_watches(parc, repo):
    """Manager + codeur dans le dépôt : le commentaire n'accuse que le codeur."""
    parc(repo, ("le-manager", "manager"), ("le-codeur", "coder"))

    mode, _reason, comment = isolation.resolve_isolation(str(repo), "shared")

    assert mode == "worktree"
    assert "le-codeur" in comment
    assert "le-manager" not in comment, "un read-only ne doit jamais être accusé de collision"


# ── les autres décisions ne bougent pas ─────────────────────────────────────

def test_an_explicit_worktree_request_never_consults_the_parc(parc, repo):
    """Demander `worktree+venv` est respecté tel quel, dépôt occupé ou non."""
    parc(repo, ("codeur-en-place", "coder"))

    mode, _reason, comment = isolation.resolve_isolation(str(repo), "worktree+venv")

    assert mode == "worktree+venv" and comment == ""
