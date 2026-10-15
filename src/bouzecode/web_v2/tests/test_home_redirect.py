import pytest


@pytest.fixture()
def client():
    from bouzecode.web_v2.app import create_app

    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_root_redirects_to_bureau(client):
    """Le Bureau est la page d'accueil (SPEC §0) : ce qui m'attend, puis mon travail."""
    resp = client.get("/")
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/bureau")


def test_old_session_page_redirects_to_the_agent_panel(client):
    """/sessions/<key> ouvre désormais le panneau de l'agent dans /conversations."""
    resp = client.get("/sessions/agent/abc123")
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/conversations?agent=abc123")
    # L'ancienne page (session.html) est supprimée : ses vues vivent dans le panneau d'agent.
    assert client.get("/sessions/agent/abc123?legacy=1").status_code == 302


def test_design_system_demo_page_is_served(client):
    resp = client.get("/_ds")
    assert resp.status_code == 200
    assert "Design system" in resp.get_data(as_text=True)


def test_root_follow_renders_bureau(client):
    resp = client.get("/", follow_redirects=True)
    assert resp.status_code == 200


def test_projects_page_is_gone(client):
    """Les pages web projets ont été retirées."""
    assert client.get("/projects").status_code == 404
    assert client.get("/p/bouzecode").status_code == 404


def test_files_explorer_page_is_gone(client):
    """L'explorateur de fichiers a été retiré ; les diffs de session restent servis."""
    assert client.get("/files").status_code == 404


def test_old_todo_page_redirects_to_bureau(client):
    """L'ancienne page TO-DO : l'URL reste valide (liens, favoris) mais le Bureau la porte."""
    resp = client.get("/todo")
    assert resp.status_code in (301, 302, 308)
    assert "/bureau" in resp.headers["Location"]
