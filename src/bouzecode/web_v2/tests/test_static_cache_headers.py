"""Monaco (vendorisé) est mis en cache par le navigateur, le CSS/JS maison reste revalidé.

Sans ça, chaque ouverture de /files ou /sessions/<key> redemandait les ~1000 fichiers de
static/vendor/monaco — c'est ce que faisait l'ancien `SEND_FILE_MAX_AGE_DEFAULT = 0`.
"""

import pytest

from bouzecode.web_v2.app import VENDOR_MAX_AGE_SECONDS, create_app


@pytest.fixture
def client():
    return create_app().test_client()


def test_vendored_monaco_is_cached_for_a_long_time(client):
    """Un asset tiers immuable est servi avec un max-age long : plus aucune requête ensuite."""
    response = client.get("/static/vendor/monaco/vs/loader.js")

    assert response.status_code == 200
    assert response.cache_control.max_age == VENDOR_MAX_AGE_SECONDS


def test_hand_written_assets_are_revalidated_not_cached(client):
    """Un asset maison n'est jamais figé : le navigateur revalide, une édition est visible."""
    response = client.get("/static/js/conversations.js")

    assert response.status_code == 200
    assert not response.cache_control.max_age
    assert response.cache_control.no_cache
