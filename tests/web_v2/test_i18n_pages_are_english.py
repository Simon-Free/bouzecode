# [desc] Les trois pages sont servies en ANGLAIS et portent le sélecteur de langue. [/desc]
"""L'anglais est la langue par défaut, et il est DANS le HTML servi.

Ce n'est pas un détail de goût : c'est ce qui garantit qu'aucun texte français n'apparaît une
fraction de seconde avant d'être réécrit. Le serveur ne négocie aucune langue — il rend
l'anglais, avec les clés de traduction en attributs, et le client réécrit s'il faut du
français. Un gabarit qui laisserait passer un mot français le ferait donc voir à TOUT le
monde, y compris aux utilisateurs anglophones qui n'ont pas de bascule à faire.
"""
from __future__ import annotations

import re

import pytest

PAGES = ["/conversations", "/agent-builder"]
# Les accents suffisent à repérer du français dans un gabarit anglais : aucun libellé anglais
# de cette interface n'en porte.
ACCENTED = re.compile(r"[éèêëàâçùûôîïœÉÈÊÀÂÇÙÔÎ]")


@pytest.fixture()
def client():
    from bouzecode.web_v2.app import create_app
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def _body(client, path: str) -> str:
    resp = client.get(path)
    assert resp.status_code == 200
    return resp.get_data(as_text=True)


@pytest.mark.parametrize("path", PAGES)
def test_the_served_page_declares_english(client, path):
    assert '<html lang="en">' in _body(client, path)


@pytest.mark.parametrize("path", PAGES)
def test_the_served_page_offers_both_languages(client, path):
    html = _body(client, path)

    assert 'id="lang-switch"' in html
    assert '<option value="en">' in html
    assert '<option value="fr">' in html


@pytest.mark.parametrize("path", PAGES)
def test_the_served_page_loads_both_dictionaries(client, path):
    html = _body(client, path)

    assert "js/i18n/core.js" in html
    assert "js/i18n/en/common.js" in html
    assert "js/i18n/fr/common.js" in html


@pytest.mark.parametrize("path", PAGES)
def test_no_french_word_is_baked_into_the_page_body(client, path):
    """Le corps servi est intégralement anglais — pas un mot à réécrire au premier rendu.

    On retire d'abord ce qui ne s'affiche jamais : les scripts et les feuilles de style
    inline, dont les commentaires sont en français comme tout le reste du code."""
    body = _body(client, path).split("<body", 1)[1]
    for tag in ("script", "style"):
        body = re.sub(rf"<{tag}\b.*?</{tag}>", "", body, flags=re.S)

    accents = ACCENTED.findall(body)
    assert not accents, f"français dans le HTML servi de {path} : {set(accents)}"


def test_a_translation_key_travels_with_the_rendered_conversation_blocks():
    """Le chrome des blocs rendus par le serveur porte sa clé, sinon le client ne peut rien
    traduire une fois le HTML inséré."""
    from bouzecode.web_v2.services import message_view

    html = message_view.render_message(
        {"role": "tool", "name": "Bash", "content": "hello"}
    )

    assert 'data-i18n="block.tool_result"' in html
    assert 'data-i18n-arg-name="Bash"' in html
