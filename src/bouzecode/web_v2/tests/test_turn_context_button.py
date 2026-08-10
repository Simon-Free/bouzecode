"""Test render_message : le bouton « ? » (contexte du tour) apparaît dans la
bulle assistant seulement quand un context_url est fourni.

Design rétabli depuis le stash : le bouton « ? » est un lien <a href> qui ouvre
la page de diagnostic du contexte (/api/sessions/<key>/turns/<n>/context) dans
un nouvel onglet — pas un <button> déclenchant un modal JS. Ce design fonctionne
sur toutes les pages (session ET /conversations) sans dépendre d'un handler JS.
"""
from bouzecode.web_v2.services import message_view

ASSISTANT_MSG = {
    "role": "assistant",
    "content": "Réponse de l'assistant.",
    "tool_calls": [{"id": "b1", "function": {"name": "Bash"}}],
}

CONTEXT_URL = "/api/sessions/mykey/turns/3/context"


def test_assistant_block_has_context_link_with_context_url():
    html = message_view.render_message(ASSISTANT_MSG, context_url=CONTEXT_URL)
    assert 'class="turn-context-help"' in html
    assert f'href="{CONTEXT_URL}"' in html
    assert 'target="_blank"' in html
    assert 'rel="noopener"' in html
    # Le lien porte le libellé « ? »
    assert ">?</a>" in html


def test_assistant_block_without_context_url_has_no_link():
    html = message_view.render_message(ASSISTANT_MSG)
    assert "turn-context-help" not in html


def test_user_block_never_has_context_link():
    html = message_view.render_message(
        {"role": "user", "content": "salut"}, context_url=CONTEXT_URL
    )
    assert "turn-context-help" not in html
