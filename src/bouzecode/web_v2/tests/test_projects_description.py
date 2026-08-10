# [desc] Tests pytest de la feature descriptions de projets : PATCH/GET/POST du registre. [/desc]
"""Feature descriptions de projets.

- PATCH /api/projects/<slug> {description} persiste dans projects.json.
- GET /api/projects renvoie la description.
- POST /api/projects accepte une description a la creation.
"""
import json

import pytest

from bouzecode.web_v2.app import create_app
from bouzecode.web_v2.services.work import projects


@pytest.fixture()
def projects_file(tmp_path, monkeypatch):
    """Redirige PROJECTS_PATH vers un fichier tmp avec un projet."""
    path = tmp_path / "projects.json"
    path.write_text(
        json.dumps(
            [{"name": "Bouzecode", "slug": "bouzecode", "path": str(tmp_path)}],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(projects, "PROJECTS_PATH", path)
    # Vider le cache d'overview pour ne pas servir un état périmé.
    monkeypatch.setattr(projects, "_overview_cache", {}, raising=False)
    return path


@pytest.fixture()
def client(projects_file):
    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client()


def test_patch_persiste_description(client, projects_file):
    resp = client.patch("/api/projects/bouzecode", json={"description": "Agent de code TDD"})
    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = resp.get_json()
    assert body["description"] == "Agent de code TDD"

    stored = json.loads(projects_file.read_text(encoding="utf-8"))
    assert stored[0]["description"] == "Agent de code TDD"


def test_patch_slug_inconnu_404(client):
    resp = client.patch("/api/projects/inexistant", json={"description": "x"})
    assert resp.status_code == 404


def test_get_projects_renvoie_description(client):
    client.patch("/api/projects/bouzecode", json={"description": "Ma desc GET"})
    # On lit directement le registre pour éviter le cache d'overview.
    stored = projects.list_projects()
    assert stored[0]["description"] == "Ma desc GET"


def test_post_projects_accepte_description(client, tmp_path):
    resp = client.post(
        "/api/projects",
        json={"name": "Demo App", "path": str(tmp_path), "description": "Desc création"},
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = resp.get_json()
    assert body["description"] == "Desc création"
