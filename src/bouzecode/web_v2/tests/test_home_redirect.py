import pytest


@pytest.fixture()
def client():
    from bouzecode.web_v2.app import create_app

    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_root_redirects_to_conversations(client):
    resp = client.get("/")
    assert resp.status_code == 302
    assert "/conversations" in resp.headers["Location"]


def test_root_follow_renders_conversations(client):
    resp = client.get("/", follow_redirects=True)
    assert resp.status_code == 200


def test_projects_page_is_gone(client):
    """Les pages web projets ont été retirées : l'UI est centrée sur /conversations."""
    assert client.get("/projects").status_code == 404
    assert client.get("/p/bouzecode").status_code == 404


def test_files_explorer_page_is_gone(client):
    """L'explorateur de fichiers a été retiré ; les diffs de session restent servis."""
    assert client.get("/files").status_code == 404
