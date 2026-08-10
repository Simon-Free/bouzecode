"""Layout test for the /conversations page.

Historique : une refonte antérieure avait RETIRÉ toute création de conversation de
cette page (jugée redondante avec l'accueil). Le user la veut de retour, façon
Claude/ChatGPT : une simple barre de prompt + une flèche d'envoi, en tête du panneau
droit (envoi sur /api/dispatch). Ce test verrouille donc la PRÉSENCE de ce composeur,
l'ABSENCE du bouton 'Nettoyer les tests' (exclusion auto côté backend), et la
structure de base (liste à gauche, onglets/panneaux à droite).
"""
import re

import pytest


@pytest.fixture()
def client():
    from bouzecode.web_v2.app import create_app

    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def _extract(html, tag, cls):
    """Return the inner HTML of the first <tag class="...cls..."> ... </tag>."""
    open_re = re.compile(rf'<{tag}\b[^>]*class="[^"]*\b{re.escape(cls)}\b[^"]*"[^>]*>')
    m = open_re.search(html)
    assert m, f"<{tag} class={cls}> not found"
    start = m.end()
    depth = 1
    tag_re = re.compile(rf'</?{tag}\b')
    for tm in tag_re.finditer(html, start):
        if html[tm.start():tm.start() + 2] == "</":
            depth -= 1
            if depth == 0:
                return html[start:tm.start()]
        else:
            depth += 1
    raise AssertionError(f"unbalanced <{tag}>")


def test_new_conversation_composer_exists(client):
    """La barre de prompt 'nouvelle conversation' (champ + flèche d'envoi) doit exister
    dans le panneau droit, façon Claude/ChatGPT."""
    resp = client.get("/conversations")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    right = _extract(html, "section", "conv-main")
    assert 'id="conv-new-bar"' in right
    assert 'id="conv-new-input"' in right
    assert 'id="conv-new-send"' in right


def test_purge_tests_button_is_removed(client):
    """Le bouton 'Nettoyer les tests' est retiré (exclusion auto côté backend)."""
    resp = client.get("/conversations")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    assert 'id="purge-test-btn"' not in html
    assert "Nettoyer les tests" not in html


def test_plus_button_to_open_a_tab_is_removed(client):
    """Le bouton "+" d'ouverture d'onglet a disparu : la barre de prompt le remplace.

    (Descendu d'un test Playwright : l'absence d'un élément dans le HTML rendu se lit
    directement dans la réponse, sans navigateur.)"""
    html = client.get("/conversations").get_data(as_text=True)

    assert "conv-new-tab-btn" not in html


def test_base_layout_is_intact(client):
    """Structure conservée : liste à gauche (aside.conv-sidebar), onglets/panneaux à droite."""
    resp = client.get("/conversations")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)

    left = _extract(html, "aside", "conv-sidebar")
    right = _extract(html, "section", "conv-main")

    # La liste des conversations reste dans le panneau gauche.
    assert 'id="conv-list"' in left
    # Les onglets et panneaux restent dans le panneau droit.
    assert 'id="conv-tabs"' in right
    assert 'id="conv-panels"' in right
