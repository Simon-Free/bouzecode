"""Un enfant dispatché par un manager HÉRITE du projet de son manager.

Un manager n'a aucun moyen de connaître les slugs de projets : c'est le serveur qui
remonte de son agent_id (`parent`) jusqu'à son projet. Sans cet héritage, CHAQUE dispatch
d'un manager repartait en `needs_project` — zéro enfant créé, mission morte en silence.
Un `project_slug` explicite prime toujours, et le lancement manuel de l'UI est intact.
"""
from __future__ import annotations

import json

import pytest

from bouzecode.web_v2.runtime import runner
from bouzecode.web_v2.services.work import dispatch, projects

SLUG = "demo-app"
OTHER_SLUG = "demo-ingestion"
MANAGER_ID = "0123456789ab"


@pytest.fixture()
def open_projects(tmp_path):
    """Deux projets ouverts sur le board, chacun avec son dossier (non-git → isolation shared)."""
    entries = []
    for slug, name in ((SLUG, "demo_app"), (OTHER_SLUG, "demo_ingestion")):
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
    monkeypatch.setattr(runner, "AGENTS_DIR", directory)
    return directory


def _write_manager(agents_dir, cwd: str, ticket_slug: str) -> str:
    """Un manager DÉJÀ lancé, tel que le serveur l'a persisté à son spawn."""
    (agents_dir / f"{MANAGER_ID}.json").write_text(json.dumps({
        "agent_id": MANAGER_ID, "prompt": "orchestre la mission", "model": "opus",
        "cwd": cwd, "pid": 4242, "started_at": "2026-07-27T10:00:00",
        "ticket_slug": ticket_slug, "ticket_id": "beefcafe", "parent": "dispatcher:manual",
    }), encoding="utf-8")
    return MANAGER_ID


@pytest.fixture()
def launched(monkeypatch):
    """Remplace la partie LOURDE (worktree + spawn de process) par un enregistrement."""
    calls: list[dict] = []

    class _SpawnedAgent:
        agent_id = "enfant-1"

    # `**_` : ce test n'observe QUE le routage (slug/projet/parent). Épingler la liste
    # exhaustive des arguments de `_launch` le faisait casser à chaque nouvelle option de
    # dispatch (work_branch…) alors que le comportement testé n'avait pas bougé.
    def fake_launch(slug, ticket, project_path, profile, model,
                    isolation="", parent="", *_, **__):
        calls.append({"slug": slug, "project_path": project_path, "parent": parent})
        return _SpawnedAgent()

    monkeypatch.setattr(dispatch, "_launch", fake_launch)
    return calls


def test_a_child_inherits_the_project_of_its_manager(open_projects, agents_dir, launched):
    """Le manager dispatche sans nommer de projet : l'enfant naît dans CELUI du manager."""
    parent = _write_manager(agents_dir, open_projects[0]["path"], SLUG)

    decision = dispatch.dispatch("répare la boucle", parent=parent)

    assert decision["routed"] is True
    assert decision["project_slug"] == SLUG
    assert launched[0]["slug"] == SLUG


def test_a_manager_working_in_a_worktree_still_finds_its_project(open_projects, agents_dir,
                                                                 launched, tmp_path):
    """Un manager isolé travaille HORS du dossier du projet et hérite quand même du bon."""
    # Un worktree vit sous ~/.bouzecode/worktrees/… : le cwd ne dit RIEN du projet, seul le
    # slug enregistré au spawn le sait. C'est pourquoi il est consulté en premier.
    worktree = tmp_path / "worktrees" / "demo_app" / "beefcafe"
    worktree.mkdir(parents=True)
    parent = _write_manager(agents_dir, str(worktree), SLUG)

    decision = dispatch.dispatch("répare la boucle", parent=parent)

    assert decision["project_slug"] == SLUG


def test_an_explicit_project_slug_wins_over_the_inherited_one(open_projects, agents_dir,
                                                              launched):
    """Le manager peut dispatcher dans un AUTRE projet en le nommant explicitement."""
    parent = _write_manager(agents_dir, open_projects[0]["path"], SLUG)

    decision = dispatch.dispatch("ingère les données", project_slug=OTHER_SLUG, parent=parent)

    assert decision["project_slug"] == OTHER_SLUG
    assert launched[0]["slug"] == OTHER_SLUG


def test_the_manual_ui_launch_still_needs_a_chosen_project(open_projects, agents_dir, launched):
    """Le lancement manuel depuis l'UI n'hérite de rien : sans projet, il en réclame un."""
    decision = dispatch.dispatch("un besoin flou")

    assert decision["needs_project"] is True
    assert decision["routed"] is False
    assert launched == []


def test_the_manual_ui_launch_with_a_chosen_project_still_works(open_projects, agents_dir,
                                                                launched):
    """Le lancement manuel avec projet choisi (la voie de l'UI) reste inchangé."""
    decision = dispatch.dispatch("répare la boucle", project_slug=SLUG,
                                 parent=dispatch._MANUAL_PARENT)

    assert decision["routed"] is True
    assert decision["project_slug"] == SLUG
    assert launched[0]["parent"] == dispatch._MANUAL_PARENT


def test_a_parent_attached_to_no_open_project_asks_for_one(open_projects, agents_dir, launched):
    """Un parent rattaché à un projet fermé n'invente pas de projet : il en réclame un."""
    parent = _write_manager(agents_dir, "/nulle/part", "projet-referme")

    decision = dispatch.dispatch("répare la boucle", parent=parent)

    assert decision["needs_project"] is True
    assert launched == []
