# [desc] Ouvrir, refuser en double et refermer un projet, via le service et via DELETE /api/projects/<slug>. [/desc]
"""Le registre des projets ouverts : on ouvre un dossier, on ne l'ouvre pas deux fois, on le referme.

POST/GET/PATCH sont déjà couverts par src/bouzecode/web_v2/tests/test_projects_description.py ;
ce fichier couvre ce qui ne l'était pas : le refus des doublons, l'ouverture d'un dossier
inexistant, et la fermeture (DELETE) d'un projet.
"""
import pytest

from bouzecode.web_v2.app import create_app
from bouzecode.web_v2.services.work import projects, tickets, worktrees


@pytest.fixture(autouse=True)
def isolated_registry(tmp_path, monkeypatch):
    """Registre, tickets et worktrees redirigés sous tmp : aucun test ne touche l'état réel."""
    monkeypatch.setattr(projects, "PROJECTS_PATH", tmp_path / "projects.json")
    monkeypatch.setattr(tickets, "TICKETS_DIR", tmp_path / "tickets")
    monkeypatch.setattr(worktrees, "WORKTREES_DIR", tmp_path / "worktrees")
    monkeypatch.setattr(projects, "_overview_cache", {}, raising=False)


@pytest.fixture
def project_dir(tmp_path):
    """Un vrai dossier sur disque — add_project refuse un chemin inexistant."""
    path = tmp_path / "monprojet"
    path.mkdir()
    return path


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_registry_starts_empty():
    """Sans projects.json, le registre est vide."""
    assert projects.list_projects() == []


def test_opening_a_folder_registers_it(project_dir):
    """Ouvrir un dossier l'inscrit au registre sous un slug dérivé de son nom."""
    created = projects.add_project("Mon Projet", str(project_dir))

    assert created["slug"] == "mon-projet"
    assert projects.list_projects() == [created]


def test_opening_the_same_project_twice_is_refused(project_dir):
    """Un projet déjà ouvert n'est pas réinscrit : le second appel renvoie une erreur."""
    projects.add_project("Mon Projet", str(project_dir))

    second = projects.add_project("Mon Projet", str(project_dir))

    assert isinstance(second, str)
    assert "mon-projet" in second
    assert len(projects.list_projects()) == 1


def test_opening_a_missing_folder_is_refused(tmp_path):
    """Ouvrir un dossier qui n'existe pas renvoie une erreur, sans rien inscrire."""
    result = projects.add_project("Fantome", str(tmp_path / "nexiste-pas"))

    assert isinstance(result, str)
    assert projects.list_projects() == []


def test_closing_a_project_removes_it(project_dir):
    """Refermer un projet le retire du registre."""
    projects.add_project("Mon Projet", str(project_dir))

    assert projects.remove_project("mon-projet") is True
    assert projects.list_projects() == []


def test_closing_an_unknown_project_reports_failure():
    """Refermer un projet inconnu ne prétend pas avoir réussi."""
    assert projects.remove_project("jamais-ouvert") is False


def test_delete_route_closes_the_project(client, project_dir):
    """DELETE /api/projects/<slug> referme le projet et le fait disparaître du registre."""
    projects.add_project("Mon Projet", str(project_dir))

    resp = client.delete("/api/projects/mon-projet")

    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True
    assert projects.list_projects() == []


def test_delete_route_on_unknown_project_returns_404(client):
    """DELETE sur un slug inconnu répond 404."""
    resp = client.delete("/api/projects/jamais-ouvert")

    assert resp.status_code == 404
