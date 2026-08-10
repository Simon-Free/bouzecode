# [desc] Relancer un ticket passe par le même garde-fou anti-collision que le lancement initial. [/desc]
"""Relancer un ticket crashé, c'est lancer un agent — et donc devoir répondre à « le dépôt
principal est-il déjà occupé par un écrivain ? ».

`POST /api/tickets/<slug>/<id>/launch` n'appelait JAMAIS `resolve_isolation` : sans
`isolation` dans le payload, il repartait droit dans `project["path"]`. Un ticket relancé
pouvait donc atterrir dans le dépôt principal par-dessus un agent qui y écrivait déjà,
et les deux s'écrasaient — exactement ce que le garde-fou existe pour empêcher.

Le parc d'agents est peuplé avec de VRAIS profils builtin : c'est bien la whitelist
`tools:` réellement accordée qui décide qui « occupe » le dépôt."""
from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from bouzecode.web_v2 import api_sanity
from bouzecode.web_v2.routes.work import tickets as troute
from bouzecode.web_v2.runtime import runner
from bouzecode.web_v2.services.sessions import store
from bouzecode.web_v2.services.work import isolation, tickets

SLUG = "proj"
WORKTREE = "/le/worktree/du/ticket"


class _Agent:
    """Un agent du parc, tel que `runner.list_agents()` le rend : un cwd et un profil."""

    def __init__(self, agent_id: str, cwd: str, profile: str):
        self.agent_id, self.cwd, self.profile = agent_id, cwd, profile


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    """Un dépôt git minimal, comme un projet réel ouvert dans l'UI."""
    root = tmp_path / "projet"
    root.mkdir()
    for args in (("init", "-q"), ("config", "user.email", "t@t.t"), ("config", "user.name", "t")):
        assert subprocess.run(["git", *args], cwd=root, capture_output=True).returncode == 0
    return root


@pytest.fixture()
def relaunch(monkeypatch, repo):
    """Relance un ticket via l'API RÉELLE. On n'espionne que le provisionnement du worktree
    et le spawn ; le store de tickets et le garde-fou d'isolation sont les vrais."""
    from bouzecode.web_v2.app import create_app

    monkeypatch.setattr(api_sanity, "require_api_sanity", lambda: None)
    monkeypatch.setattr(troute, "_project_or_404",
                        lambda slug: ({"path": str(repo), "name": "P", "slug": slug}, None))
    monkeypatch.setattr(troute.dispatch, "reisolate", lambda slug, ticket, path: WORKTREE)
    spawned: dict = {}
    monkeypatch.setattr(troute.runner, "create_agent",
                        lambda prompt, model, cwd, **kw: spawned.update(cwd=cwd)
                        or SimpleNamespace(agent_id="relance-1"))

    app = create_app()
    app.config["TESTING"] = True

    def _post(payload: dict, recorded_isolation: str = "") -> dict:
        ticket = tickets.create_ticket(SLUG, "ticket planté", "refais-le")
        if recorded_isolation:
            ticket["isolation"] = recorded_isolation
            tickets.update_ticket(SLUG, ticket)
        with app.test_client() as client:
            response = client.post(f"/api/tickets/{SLUG}/{ticket['id']}/launch", json=payload)
        assert response.status_code == 200, response.get_data(as_text=True)
        return {"cwd": spawned["cwd"], "ticket": tickets.get_ticket(SLUG, ticket["id"])}

    return _post


@pytest.fixture()
def parc(monkeypatch, repo):
    """Peuple le dépôt principal d'agents « running » aux profils donnés."""

    def _install(*profiles: tuple[str, str]) -> None:
        agents = [_Agent(agent_id, str(repo), profile) for agent_id, profile in profiles]
        monkeypatch.setattr(runner, "list_agents", lambda: agents)
        monkeypatch.setattr(store, "agent_status", lambda a: {"state": "running"})

    return _install


# ── le trou : une relance dans un dépôt déjà occupé ──────────────────────────

def test_a_relaunch_into_a_busy_repo_gets_its_own_worktree(relaunch, parc):
    """Un codeur écrit déjà dans le dépôt principal : le ticket relancé est isolé d'office."""
    parc(("codeur-en-place", "coder"))

    result = relaunch({})

    assert result["cwd"] == WORKTREE, "la relance ne doit pas atterrir sur un écrivain actif"
    assert result["ticket"]["isolation"] == "worktree"


def test_the_relaunched_ticket_is_told_why_it_was_isolated(relaunch, parc):
    """Le rattrapage est EXPLIQUÉ sur le ticket, jamais silencieux."""
    parc(("codeur-en-place", "coder"))

    comment = relaunch({})["ticket"]["comments"][0]["text"]

    assert "codeur-en-place" in comment and "worktree" in comment


# ── ce que le garde-fou ne doit PAS faire ────────────────────────────────────

def test_a_lone_relaunch_stays_in_the_main_repo(relaunch, parc, repo):
    """Dépôt libre : la relance reste « shared », sans worktree ni commentaire."""
    parc()

    result = relaunch({})

    assert result["cwd"] == str(repo)
    assert result["ticket"]["comments"] == []


def test_a_read_only_manager_does_not_force_a_worktree(relaunch, parc, repo):
    """Un manager read-only actif dans le dépôt n'écrase personne : il n'isole personne."""
    parc(("le-manager", "manager"))

    assert relaunch({})["cwd"] == str(repo)


# ── l'isolation explicite reste maîtresse ────────────────────────────────────

def test_an_explicit_isolation_request_is_honoured(relaunch, parc):
    """`isolation` demandée dans le payload est respectée telle quelle, dépôt libre ou non."""
    parc()

    result = relaunch({"isolation": "worktree+venv"})

    assert result["cwd"] == WORKTREE
    assert result["ticket"]["isolation"] == "worktree+venv"


def test_the_isolation_recorded_on_the_ticket_is_kept(relaunch, parc):
    """Sans rien dans le payload, la relance garde l'isolation déjà inscrite sur le ticket."""
    parc()

    result = relaunch({}, recorded_isolation="worktree")

    assert result["cwd"] == WORKTREE
    assert result["ticket"]["isolation"] == "worktree"
