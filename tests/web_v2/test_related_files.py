"""Fichiers livrés (`related_files`) d'un rendu de tâche, et route POST /api/fichiers/ouvrir.

Le rendu humain accepte `related_files` (persisté, relu en GET) ; la route d'ouverture n'ouvre
que des chemins DÉCLARÉS par une livraison connue (403 sinon), 404 si le fichier a disparu.
L'« ouvreur » est injecté via `app.config["BOUZECODE_FILE_OPENER"]` : aucune application réelle
n'est lancée."""
import os

import pytest

from tests.web_v2.test_payload_leger import ctx  # noqa: F401 — fixture réutilisée
from tests.web_v2.test_rendu_humain import _rendu, depot  # noqa: F401 — fixture réutilisée


def _meme(a, b):
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


@pytest.fixture
def ouverts(ctx):  # noqa: F811
    client, _macro, _micro = ctx
    liste: list = []
    client.application.config["BOUZECODE_FILE_OPENER"] = lambda chemin: liste.append(str(chemin))
    yield liste
    client.application.config.pop("BOUZECODE_FILE_OPENER", None)


@pytest.fixture
def livre(ctx, depot, tmp_path):  # noqa: F811
    """Un rendu accepté qui déclare un rapport .html existant."""
    client, _macro, micro_id = ctx
    rapport = tmp_path / "rapport.html"
    rapport.write_text("<h1>ok</h1>", encoding="utf-8")
    r = client.post(f"/api/micros/{micro_id}/rendu", json=_rendu(
        depot, related_files=[{"path": str(rapport), "label": "Rapport", "kind": "html"}]))
    assert r.status_code == 201, r.data
    return rapport


def test_rendu_persiste_related_files(ctx, livre):  # noqa: F811
    client, _macro, micro_id = ctx
    relu = client.get(f"/api/micros/{micro_id}/rendu").get_json()["rendu"]
    fichiers = relu["related_files"]
    assert len(fichiers) == 1, fichiers
    assert _meme(fichiers[0]["path"], livre)
    assert fichiers[0]["label"] == "Rapport"
    assert fichiers[0]["kind"] == "html"


def test_ouvrir_chemin_non_declare_403(ctx, livre, ouverts, tmp_path):  # noqa: F811
    client, _macro, micro_id = ctx
    autre = tmp_path / "secret.txt"
    autre.write_text("x", encoding="utf-8")
    r = client.post("/api/fichiers/ouvrir", json={"path": str(autre), "micro_id": micro_id})
    assert r.status_code == 403, r.data
    assert ouverts == []


def test_ouvrir_livraison_inconnue_403(ctx, livre, ouverts):  # noqa: F811
    client, _macro, _micro = ctx
    r = client.post("/api/fichiers/ouvrir", json={"path": str(livre), "micro_id": "inconnu-xyz"})
    assert r.status_code == 403, r.data
    assert ouverts == []


def test_ouvrir_fichier_absent_404(ctx, livre, ouverts):  # noqa: F811
    client, _macro, micro_id = ctx
    livre.unlink()
    r = client.post("/api/fichiers/ouvrir", json={"path": str(livre), "micro_id": micro_id})
    assert r.status_code == 404, r.data
    assert ouverts == []


def test_ouvrir_fichier_declare_200(ctx, livre, ouverts):  # noqa: F811
    client, _macro, micro_id = ctx
    r = client.post("/api/fichiers/ouvrir", json={"path": str(livre), "micro_id": micro_id})
    assert r.status_code == 200, r.data
    assert r.get_json() == {"ok": True}
    assert len(ouverts) == 1 and _meme(ouverts[0], livre)
