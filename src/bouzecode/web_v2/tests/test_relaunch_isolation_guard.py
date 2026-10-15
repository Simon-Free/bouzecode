# [desc] Relancer un ticket passe par le même garde-fou anti-collision que le lancement initial. [/desc]
"""Relancer un ticket crashé, c'est lancer un agent — et donc devoir répondre à « le dépôt
principal est-il déjà occupé par un écrivain ? ».

`POST /api/projects/<slug>/tickets/<id>/runs` relance avec l'isolation DU TICKET (C8). Un ticket
`shared` relancé dans un dépôt où un autre agent écrit déjà est REFUSÉ (409
`collision_isolation`) : le serveur ne bascule plus jamais en worktree d'office (spec §5.1).

Le parc d'agents est peuplé avec de VRAIS profils builtin : c'est bien la whitelist
`tools:` réellement accordée qui décide qui « occupe » le dépôt."""
from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from bouzecode.web_v2 import api_sanity
from bouzecode.web_v2.runtime.runner import agent_creation, agent_registre
from bouzecode.web_v2.services.sessions import store
from bouzecode.web_v2.services.work import tickets

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
def relaunch(monkeypatch, repo, tmp_path):
    """Relance un ticket via l'API RÉELLE (`POST …/runs`). On n'espionne que le
    provisionnement du worktree et le spawn ; le store et le garde-fou sont les vrais."""
    from bouzecode.web_v2.app import create_app
    from bouzecode.web_v2.services.work import dispatch

    from aides_tickets import projet
    projet(tmp_path, monkeypatch, SLUG, chemin=repo)
    monkeypatch.setattr(api_sanity, "require_api_sanity", lambda: None)
    monkeypatch.setattr(dispatch, "reisolate", lambda slug, ticket, path: WORKTREE)
    spawned: dict = {}
    monkeypatch.setattr(agent_creation, "create_agent",
                        lambda prompt, model, cwd, **kw: spawned.update(cwd=cwd)
                        or SimpleNamespace(agent_id="relance-1"))

    app = create_app()
    app.config["TESTING"] = True

    def _post(payload: dict, recorded_isolation: str = "", attendu: int = 202) -> dict:
        ticket = tickets.create_ticket(SLUG, "ticket planté", "refais-le")
        if recorded_isolation:
            tickets.poser(SLUG, ticket, isolation=recorded_isolation)
        with app.test_client() as client:
            response = client.post(f"/api/projects/{SLUG}/tickets/{ticket['id']}/runs",
                                   json={**payload, "defer": False})
        assert response.status_code == attendu, response.get_data(as_text=True)
        return {"cwd": spawned.get("cwd"), "ticket": tickets.get_ticket(SLUG, ticket["id"]),
                "reponse": response.get_json()}

    return _post


@pytest.fixture()
def parc(monkeypatch, repo):
    """Peuple le dépôt principal d'agents « running » aux profils donnés."""

    def _install(*profiles: tuple[str, str]) -> None:
        agents = [_Agent(agent_id, str(repo), profile) for agent_id, profile in profiles]
        monkeypatch.setattr(agent_registre, "list_agents", lambda: agents)
        monkeypatch.setattr(store, "agent_status", lambda a: {"state": "running"})

    return _install


# ── une relance shared dans un dépôt déjà occupé : REFUSÉE, jamais basculée (C8) ──

def test_a_relaunch_into_a_busy_repo_is_refused_never_switched(relaunch, parc):
    """Un codeur écrit déjà dans le dépôt principal : la relance d'un ticket `shared` est
    refusée en 409 `collision_isolation` ; le serveur ne bascule JAMAIS en worktree d'office."""
    parc(("codeur-en-place", "coder"))

    result = relaunch({}, attendu=409)

    erreur = result["reponse"]["error"]
    assert erreur["code"] == "collision_isolation"
    assert erreur["details"]["agents"] == ["codeur-en-place"]
    assert result["cwd"] is None and result["ticket"]["state"] == "created"
    assert result["ticket"].get("isolation") is None


# ── ce que le garde-fou ne doit PAS faire ────────────────────────────────────

def test_a_lone_relaunch_stays_in_the_main_repo(relaunch, parc, repo):
    """Dépôt libre : la relance reste « shared », sans worktree ni commentaire."""
    parc()

    result = relaunch({})

    assert result["cwd"] == str(repo)
    assert result["ticket"]["comments"] == []


def test_a_read_only_manager_does_not_block_a_relaunch(relaunch, parc, repo):
    """Un manager read-only actif dans le dépôt n'écrase personne : il ne bloque personne."""
    parc(("le-manager", "manager"))

    assert relaunch({})["cwd"] == str(repo)


# ── l'isolation DU TICKET fait foi ───────────────────────────────────────────

def test_an_isolation_in_the_payload_does_not_rewrite_the_ticket(relaunch, parc, repo):
    """Relancer conserve l'isolation du ticket (C8) : celle du corps est ignorée."""
    parc()

    result = relaunch({"isolation": "worktree+venv"})

    assert result["cwd"] == str(repo)
    assert result["ticket"].get("isolation") is None


def test_the_isolation_recorded_on_the_ticket_is_kept(relaunch, parc):
    """Sans rien dans le payload, la relance garde l'isolation déjà inscrite sur le ticket."""
    parc()

    result = relaunch({}, recorded_isolation="worktree")

    assert result["cwd"] == WORKTREE
    assert result["ticket"]["isolation"] == "worktree"
    assert result["reponse"]["run"]["isolation"] == "worktree"
