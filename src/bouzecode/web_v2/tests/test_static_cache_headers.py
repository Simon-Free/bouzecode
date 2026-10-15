"""Hand-written CSS/JS assets are always revalidated by the browser, never frozen."""

import pytest

from bouzecode.web_v2.app import create_app


@pytest.fixture
def client():
    return create_app().test_client()


def test_hand_written_assets_are_revalidated_not_cached(client):
    """Un asset maison n'est jamais figé : le navigateur revalide, une édition est visible."""
    response = client.get("/static/js/conversations.js")

    assert response.status_code == 200
    assert not response.cache_control.max_age
    assert response.cache_control.no_cache
