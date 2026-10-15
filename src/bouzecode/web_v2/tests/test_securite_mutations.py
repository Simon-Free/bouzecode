# [desc] Spec ticketing B8 / critère 9 : une mutation /api/ sans jeton donne 401, avec un mauvais jeton 401, un corps text/plain 415 ; les GET restent libres ; le jeton survit au redémarrage. [/desc]
from __future__ import annotations

import pytest
from flask.testing import FlaskClient

from bouzecode.backend.core import jeton_local
from bouzecode.web_v2.app import create_app


@pytest.fixture()
def app():
    application = create_app()
    application.config["TESTING"] = True
    return application


def _sans_jeton(app) -> FlaskClient:
    """Le client NU de Flask : n'envoie aucun jeton, comme un onglet tiers."""
    return FlaskClient(app, app.response_class, use_cookies=True)


def test_le_jeton_est_ecrit_dans_le_home_et_reutilise_au_redemarrage(app):
    jeton = jeton_local.lire_jeton()
    assert jeton and app.config["BOUZECODE_TOKEN"] == jeton
    assert create_app().config["BOUZECODE_TOKEN"] == jeton


def test_une_mutation_sans_jeton_est_refusee_401(app):
    reponse = _sans_jeton(app).post("/api/projects", json={"name": "x", "path": "y"})
    assert reponse.status_code == 401
    assert reponse.get_json()["error"]["code"] == "jeton_manquant"


@pytest.mark.parametrize("methode", ["post", "put", "patch", "delete"])
def test_un_mauvais_jeton_est_refuse_401(app, methode):
    reponse = getattr(_sans_jeton(app), methode)(
        "/api/projects/inconnu", headers={jeton_local.EN_TETE: "faux"})
    assert reponse.status_code == 401
    assert reponse.get_json()["error"]["code"] == "jeton_invalide"


def test_un_post_text_plain_est_refuse_415(app):
    reponse = app.test_client().post("/api/projects/inconnu/tickets", data='{"prompt": "x"}',
                                     content_type="text/plain")
    assert reponse.status_code == 415
    assert reponse.get_json()["error"]["code"] == "type_contenu_invalide"


def test_un_post_sans_corps_reste_accepte(app):
    """Beaucoup de gestes n'ont pas de paramètre : un corps vide n'a pas de type à vérifier."""
    reponse = app.test_client().post("/api/projects/inconnu/tickets/abc/reopen")
    assert reponse.status_code == 404


def test_les_lectures_ne_demandent_pas_de_jeton(app):
    assert _sans_jeton(app).get("/api/projects").status_code == 200


def test_la_page_porte_le_jeton_pour_le_front(app):
    page = app.test_client().get("/conversations").get_data(as_text=True)
    assert f'name="bouzecode-token" content="{app.config["BOUZECODE_TOKEN"]}"' in page


def test_le_client_http_local_joint_le_jeton():
    from bouzecode.backend.core import local_http  # noqa: F401 — même module que les outils
    jeton = jeton_local.assurer_jeton()
    assert jeton_local.en_tetes_du_jeton() == {jeton_local.EN_TETE: jeton}
