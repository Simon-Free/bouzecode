# [desc] Le registre des dépôts se voit tout de suite dans GET /api/projects : ajout, retrait, description (cache de 5 s invalidé). [/desc]
"""SPEC §5.4 « Gérer les dépôts » : un dépôt ajouté est AUSSITÔT sélectionnable. La vue
d'ensemble `/api/projects` est mémorisée 5 s ; sans invalidation, le dépôt ajouté manquait au
sélecteur (et le dialogue le montrait absent) pendant ce délai."""
import pytest


@pytest.fixture()
def client():
    from bouzecode.web_v2.app import create_app

    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def _slugs(client):
    return {p["slug"]: p for p in client.get("/api/projects").get_json()["projects"]}


def test_un_depot_ajoute_apparait_aussitot_puis_disparait_au_retrait(client, tmp_path):
    assert "mon-depot" not in _slugs(client)          # la vue d'ensemble est mise en cache ici
    dossier = tmp_path / "mon-depot"
    dossier.mkdir()
    assert client.post("/api/projects", json={"name": "mon-depot", "path": str(dossier)}).status_code == 201
    assert "mon-depot" in _slugs(client)

    assert client.patch("/api/projects/mon-depot", json={"description": "API"}).status_code == 200
    assert _slugs(client)["mon-depot"]["description"] == "API"

    assert client.delete("/api/projects/mon-depot").status_code == 200
    assert "mon-depot" not in _slugs(client)
