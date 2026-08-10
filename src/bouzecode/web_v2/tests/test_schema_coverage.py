"""GET /api/schema décrit exactement les routes /api/ du serveur — la dérive est impossible.

C'est le contrat que le parcours P7 du SPEC promet aux LLM. Ces gardes couvrent les deux
sens de la dérive : une route ajoutée sans description, et une description qui survit à la
route qu'elle décrivait.
"""

import pytest

from bouzecode.web_v2.api_descriptions import ENDPOINT_DESCRIPTIONS
from bouzecode.web_v2.app import create_app, schema_key


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


def test_new_route_without_description_is_refused(app, client):
    """Une route /api/ sans description (ni docstring de vue, ni entrée écrite) échoue ici."""
    served = client.get("/api/schema").get_json()["endpoints"]

    undescribed = sorted(key for key, description in served.items() if not description.strip())

    assert not undescribed, (
        "Ces routes /api/ n'ont aucune description : ajoute un docstring à la vue, "
        "ou une entrée dans ENDPOINT_DESCRIPTIONS (app.py).\n" + "\n".join(undescribed)
    )


def test_description_of_a_removed_route_is_refused(app):
    """Une description écrite à la main qui ne correspond à aucune route échoue ici."""
    orphans = sorted(set(ENDPOINT_DESCRIPTIONS) - _registered_api_keys(app))

    assert not orphans, (
        "Ces entrées de ENDPOINT_DESCRIPTIONS (api_descriptions.py) ne décrivent aucune route "
        "enregistrée — route renommée/supprimée, ou faute de frappe.\n" + "\n".join(orphans)
    )


def test_schema_keeps_its_public_shape(client):
    """Le JSON servi reste {description: texte, endpoints: {'MÉTHODE /chemin': texte}}."""
    schema = client.get("/api/schema").get_json()

    assert isinstance(schema["description"], str)
    assert all(
        key.split(" ", 1)[0] in {"GET", "POST", "PUT", "PATCH", "DELETE"}
        and key.split(" ", 1)[1].startswith("/api/")
        and isinstance(description, str)
        for key, description in schema["endpoints"].items()
    )
