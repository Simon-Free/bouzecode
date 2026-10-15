"""GET /api/schema décrit exactement les routes /api/ du serveur — la dérive est impossible.

C'est le contrat que le parcours P7 du SPEC promet aux LLM. Le schéma est DÉRIVÉ : la liste des
routes vient de `app.url_map`, la description du docstring de chaque vue, le corps attendu de
`@corps_attendu` posé à côté de la route. Il n'existe plus de table écrite à la main (l'ancien
`api_descriptions.py` a été retiré au lot L6) : une route sans docstring échoue ici.
"""

import pytest

from bouzecode.web_v2.app import create_app
from bouzecode.web_v2.schema import corps_attendu, routes_api, schema_key

METHODES_MUTANTES = {"POST", "PUT", "PATCH", "DELETE"}


@pytest.fixture
def app():
    return create_app()


@pytest.fixture
def client(app):
    return app.test_client()


def _registered_api_keys(app):
    """Les clés canoniques « MÉTHODE /chemin » de toutes les routes /api/ enregistrées."""
    return {
        schema_key(rule.rule, method)
        for rule in app.url_map.iter_rules()
        if rule.rule.startswith("/api/")
        for method in rule.methods - {"HEAD", "OPTIONS"}
    }


def test_schema_lists_every_registered_api_route(app, client):
    """Toute route /api/ enregistrée apparaît telle quelle dans GET /api/schema."""
    served = client.get("/api/schema").get_json()["endpoints"]

    assert set(served) == _registered_api_keys(app)


def test_new_route_without_docstring_is_refused(app, client):
    """Une route /api/ dont la vue n'a pas de docstring échoue ici : c'est sa seule description."""
    served = client.get("/api/schema").get_json()["endpoints"]

    undescribed = sorted(key for key, description in served.items() if not description.strip())

    assert not undescribed, (
        "Ces routes /api/ n'ont aucune description : ajoute un docstring à la vue.\n"
        + "\n".join(undescribed))


def test_a_declared_body_is_served_and_only_on_mutations(app, client):
    """`@corps_attendu` atterrit dans `corps` du schéma, et seulement pour des mutations."""
    corps = client.get("/api/schema").get_json()["corps"]

    assert corps["POST /api/projects/<slug>/tickets"]["title"]
    assert set(corps) <= _registered_api_keys(app)
    assert all(cle.split(" ", 1)[0] in METHODES_MUTANTES for cle in corps)


def test_corps_attendu_does_not_wrap_the_view():
    def vue():
        """une vue"""

    assert corps_attendu(texte="requis")(vue) is vue
    assert vue.__corps_attendu__ == {"texte": "requis"}


def test_schema_keeps_its_public_shape(app, client):
    """{description, endpoints: {'MÉTHODE /chemin': texte}, corps: {'MÉTHODE /chemin': {…}}}."""
    schema = client.get("/api/schema").get_json()

    assert isinstance(schema["description"], str)
    assert all(
        key.split(" ", 1)[0] in {"GET", "POST", "PUT", "PATCH", "DELETE"}
        and key.split(" ", 1)[1].startswith("/api/")
        and isinstance(description, str)
        for key, description in schema["endpoints"].items()
    )
    assert all(isinstance(champs, dict) for champs in schema["corps"].values())
    assert len(list(routes_api(app))) == len(schema["endpoints"])
