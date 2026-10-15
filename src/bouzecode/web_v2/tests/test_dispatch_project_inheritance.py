"""Un enfant lancé par l'outil `Agent` d'un manager HÉRITE du projet de son manager.

Un manager n'a aucun moyen de connaître les slugs de projets : son client (`client_tickets`)
lit le projet sur la fiche du parent (`GET /api/agents/<parent>`) puis crée le ticket par LA
route de création (`POST /api/projects/<slug>/tickets`). Un `project_slug` explicite prime ; un
parent rattaché à aucun projet ouvert (ou inconnu du serveur) ne crée RIEN et le dit
(`projet_requis`) — le serveur ne déduit jamais de projet (arbitrage P9, lot L6).
"""
from __future__ import annotations

import json

import pytest

from bouzecode.backend.multi_agent import client_tickets
from bouzecode.web_v2 import api_sanity
from bouzecode.web_v2.runtime.runner import agent_fiche
from bouzecode.web_v2.services.work import dispatch, projects, tickets
from bouzecode.web_v2.tests.client_de_l_outil import brancher

SLUG = "demo-application"
OTHER_SLUG = "demo-ingestion"
MANAGER_ID = "9d0789f2fdca"


@pytest.fixture()
def open_projects(tmp_path):
    """Deux projets ouverts sur le board, chacun avec son dossier (non-git → isolation shared)."""
    entries = []
    for slug, name in ((SLUG, "demo_application"), (OTHER_SLUG, "demo_ingestion")):
        path = tmp_path / name
        path.mkdir()
        entries.append({"slug": slug, "name": name, "path": str(path)})
    projects.PROJECTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    projects.PROJECTS_PATH.write_text(json.dumps(entries), encoding="utf-8")
    return entries


@pytest.fixture()
def agents_dir(tmp_path, monkeypatch):
    directory = tmp_path / "web_agents"
    directory.mkdir()
    monkeypatch.setattr(agent_fiche, "AGENTS_DIR", directory)
    return directory


def _write_manager(agents_dir, cwd: str, ticket_slug: str) -> str:
    """Un manager DÉJÀ lancé, tel que le serveur l'a persisté à son spawn."""
    (agents_dir / f"{MANAGER_ID}.json").write_text(json.dumps({
        "agent_id": MANAGER_ID, "prompt": "orchestre la mission", "model": "opus",
        "cwd": cwd, "pid": 4242, "started_at": "2026-07-27T10:00:00",
        "ticket_slug": ticket_slug, "ticket_id": "642e1a3f", "parent": "dispatcher:manual",
    }), encoding="utf-8")
    return MANAGER_ID


@pytest.fixture()
def launched(monkeypatch):
    """Le client de l'outil parle à la vraie app ; seule la partie LOURDE du lancement en fond
    (worktree + spawn) est remplacée par un enregistrement."""
    from bouzecode.web_v2.app import create_app
    calls: list[dict] = []
    monkeypatch.setattr(api_sanity, "require_api_sanity", lambda: None)
    monkeypatch.setattr(dispatch, "_launch_bg", lambda slug, ticket, project_path, *args: calls.append(
        {"slug": slug, "project_path": project_path, "parent": args[3]}))
    brancher(monkeypatch, create_app().test_client())
    return calls


def _lancer(prompt: str, parent: str, project_slug: str = "") -> dict:
    return client_tickets.creer_ticket({"prompt": prompt, "parent": parent, "isolation": "shared",
                                        "project_slug": project_slug})


def _attendre(calls: list, n: int = 1) -> None:
    import time
    limite = time.monotonic() + 5
    while len(calls) < n and time.monotonic() < limite:
        time.sleep(0.02)


def test_a_child_inherits_the_project_of_its_manager(open_projects, agents_dir, launched):
    """Le manager lance sans nommer de projet : l'enfant naît dans CELUI du manager."""
    parent = _write_manager(agents_dir, open_projects[0]["path"], SLUG)

    decision = _lancer("répare la boucle", parent)

    assert decision["routed"] is True and decision["project_slug"] == SLUG
    _attendre(launched)
    assert launched[0]["slug"] == SLUG and launched[0]["parent"] == parent


def test_a_manager_working_in_a_worktree_still_finds_its_project(open_projects, agents_dir,
                                                                 launched, tmp_path):
    """Un manager isolé travaille HORS du dossier du projet et hérite quand même du bon."""
    # Un worktree vit sous ~/.bouzecode/worktrees/… : le cwd ne dit RIEN du projet, seul le
    # slug enregistré au spawn le sait. C'est pourquoi il est consulté en premier.
    worktree = tmp_path / "worktrees" / "demo_application" / "642e1a3f"
    worktree.mkdir(parents=True)
    parent = _write_manager(agents_dir, str(worktree), SLUG)

    assert _lancer("répare la boucle", parent)["project_slug"] == SLUG


def test_an_explicit_project_slug_wins_over_the_inherited_one(open_projects, agents_dir,
                                                              launched):
    """Le manager peut lancer dans un AUTRE projet en le nommant explicitement."""
    parent = _write_manager(agents_dir, open_projects[0]["path"], SLUG)

    decision = _lancer("ingère les données", parent, project_slug=OTHER_SLUG)

    assert decision["project_slug"] == OTHER_SLUG
    _attendre(launched)
    assert launched[0]["slug"] == OTHER_SLUG


def test_a_parent_attached_to_no_open_project_creates_nothing(open_projects, agents_dir,
                                                              launched):
    """Un parent rattaché à un projet fermé n'invente pas de projet : refus, rien de créé."""
    parent = _write_manager(agents_dir, "/nulle/part", "projet-referme")

    decision = _lancer("répare la boucle", parent)

    #  Le slug de SA fiche n'est plus un projet ouvert : la route de création le refuse (404).
    assert decision["routed"] is False and decision["code"] == "projet_inconnu"
    assert [t for slug in (SLUG, OTHER_SLUG) for t in tickets.list_tickets(slug)] == []


def test_a_parent_unknown_to_the_server_is_named(open_projects, agents_dir, launched):
    """Incident du 2026-07-28 : l'enregistrement du manager a disparu sous lui. Le refus le DIT
    (`parent_unknown`), au lieu d'envoyer chercher une erreur de configuration."""
    decision = _lancer("construis X", "9d0789f2fdca")

    assert decision["routed"] is False and decision["code"] == "projet_requis"
    assert decision["parent_unknown"] is True
