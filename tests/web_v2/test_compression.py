"""Compression gzip des réponses dynamiques (`web_v2/compression.py`).

Contrat : même contenu, moins d'octets, et seulement quand le client l'annonce."""
import gzip

import pytest

from bouzecode.web_v2.app import create_app


@pytest.fixture
def client():
    return create_app().test_client()


def test_json_compresse_si_accepte_et_identique_une_fois_decompresse(client):
    brut = client.get("/api/schema")
    compresse = client.get("/api/schema", headers={"Accept-Encoding": "gzip, deflate, br"})
    assert brut.status_code == compresse.status_code == 200
    assert "Content-Encoding" not in brut.headers
    assert compresse.headers["Content-Encoding"] == "gzip"
    assert "Accept-Encoding" in compresse.headers.get("Vary", "")
    assert len(compresse.data) < len(brut.data) / 2
    assert int(compresse.headers["Content-Length"]) == len(compresse.data)
    assert gzip.decompress(compresse.data) == brut.data


def test_petite_reponse_et_statique_non_compresses(client):
    petite = client.get("/api/version", headers={"Accept-Encoding": "gzip"})
    assert len(petite.get_data()) < 1024 and "Content-Encoding" not in petite.headers
    statique = client.get("/static/js/lib/ui.js", headers={"Accept-Encoding": "gzip"})
    assert statique.status_code == 200 and "Content-Encoding" not in statique.headers
    statique.close()


def test_etag_fort_devient_faible_une_fois_compresse():
    from flask import Flask, jsonify
    from bouzecode.web_v2 import compression
    app = Flask("essai")
    compression.installer(app)

    @app.get("/gros")
    def gros():
        resp = jsonify({"x": "y" * 5000})
        resp.set_etag("abc")
        return resp

    resp = app.test_client().get("/gros", headers={"Accept-Encoding": "gzip"})
    assert resp.headers["Content-Encoding"] == "gzip"
    assert resp.headers["ETag"] == 'W/"abc"'
