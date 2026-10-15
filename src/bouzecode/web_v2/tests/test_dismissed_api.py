# [desc] Tests des routes du registre à trois états : lister, écarter, annuler un écart. [/desc]
"""API du registre de projets, versant « non ».

Un « ce n'est pas un projet » donné trop vite doit rester annulable depuis
l'interface : sans ça il serait définitif et invisible.
"""
import json

import pytest

from bouzecode.web_v2.app import create_app
from bouzecode.web_v2.services.work import dismissed_paths, projects


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(dismissed_paths, "DISMISSED_PATH", tmp_path / "dismissed.json")
    monkeypatch.setattr(projects, "PROJECTS_PATH", tmp_path / "projects.json")
    monkeypatch.setattr(projects, "_overview_cache", {}, raising=False)
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        c.tmp_path = tmp_path
        yield c


def test_la_liste_est_vide_au_depart(client):
    reponse = client.get("/api/projects/dismissed")

    assert reponse.status_code == 200
    assert reponse.get_json()["dismissed"] == []


def test_ecarter_un_dossier_puis_le_relire(client):
    dossier = client.tmp_path / "demo"
    dossier.mkdir()

    ajout = client.post("/api/projects/dismissed",
                        json={"path": str(dossier), "reason": "conteneur"})
    assert ajout.status_code == 200

    liste = client.get("/api/projects/dismissed").get_json()["dismissed"]
    assert len(liste) == 1
    assert liste[0]["reason"] == "conteneur"


def test_annuler_un_ecart_le_retire_de_la_liste(client):
    dossier = client.tmp_path / "demo"
    dossier.mkdir()
    client.post("/api/projects/dismissed", json={"path": str(dossier)})

    suppression = client.delete("/api/projects/dismissed", json={"path": str(dossier)})

    assert suppression.status_code == 200
    assert client.get("/api/projects/dismissed").get_json()["dismissed"] == []


def test_annuler_un_ecart_inexistant_repond_404(client):
    reponse = client.delete("/api/projects/dismissed", json={"path": str(client.tmp_path)})

    assert reponse.status_code == 404


def test_un_chemin_manquant_est_refuse(client):
    assert client.post("/api/projects/dismissed", json={}).status_code == 400
    assert client.delete("/api/projects/dismissed", json={}).status_code == 400


def test_ajouter_un_projet_ecarte_leve_l_ecart(client):
    """Se raviser depuis l'interface doit fonctionner de bout en bout."""
    dossier = client.tmp_path / "demo_ingestion"
    dossier.mkdir()
    client.post("/api/projects/dismissed", json={"path": str(dossier)})

    ajout = client.post("/api/projects",
                        json={"name": "demo_ingestion", "path": str(dossier)})

    assert ajout.status_code == 201
    assert client.get("/api/projects/dismissed").get_json()["dismissed"] == []


def test_les_ecartes_n_apparaissent_pas_dans_la_liste_de_lancement(client):
    """Deux fichiers séparés, justement pour que les non-projets ne polluent pas
    la liste que l'interface affiche au lancement d'un agent."""
    dossier = client.tmp_path / "demo"
    dossier.mkdir()
    client.post("/api/projects/dismissed", json={"path": str(dossier)})

    assert projects.list_projects() == []
    ecarte = json.loads((client.tmp_path / "dismissed.json").read_text(encoding="utf-8"))
    assert [e["path"] for e in ecarte] == [str(dossier.resolve())]
