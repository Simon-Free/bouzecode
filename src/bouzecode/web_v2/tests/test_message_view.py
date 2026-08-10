# [desc] Tests pytest du rendu HTML de message_view : thinking en italique/stripé + data-attrs d'appariement call/result. [/desc]
"""Tests user-centric du rendu HTML d'un message de conversation ouverte.

On appelle la vraie fonction publique render_message et on vérifie le HTML
produit (ce que le navigateur reçoit via /api/sessions/<key>/blocks).
"""
from __future__ import annotations

from bouzecode.web_v2.services import message_view


def test_thinking_rendered_italic_and_stripped_from_text():
    """Le <thinking> devient un bloc italique .thinking et disparait du texte visible."""
    message = {
        "role": "assistant",
        "content": "<thinking>\nje reflechis ici\n</thinking>\nVoici ma reponse visible.",
        "tool_calls": [],
    }

    html = message_view.render_message(message)

    # (a) thinking rendu en italique dans un bloc dedie
    assert 'class="thinking' in html
    assert "<em>je reflechis ici</em>" in html
    # les balises <thinking> brutes ne doivent PAS apparaitre
    assert "&lt;thinking&gt;" not in html
    assert "<thinking>" not in html
    # le texte visible reste rendu
    assert "Voici ma reponse visible." in html


def test_thinking_multiline_newlines_become_br():
    message = {
        "role": "assistant",
        "content": "<thinking>\nligne un\nligne deux\n</thinking>\ntexte",
    }

    html = message_view.render_message(message)

    assert "ligne un<br>ligne deux" in html


def test_no_thinking_block_leaves_text_intact():
    message = {"role": "assistant", "content": "juste du texte, pas de thinking"}

    html = message_view.render_message(message)

    assert '<div class="thinking">' not in html
    assert "juste du texte, pas de thinking" in html


def test_tool_call_carries_data_tool_id():
    """Le call porte data-tool-id pour permettre l'appariement cote client (b)."""
    message = {
        "role": "assistant",
        "content": "",
        "tool_calls": [{"id": "call_42", "name": "Bash", "input": {"command": "ls"}}],
    }

    html = message_view.render_message(message)

    assert 'data-tool-id="call_42"' in html
    assert 'class="tc' in html


def test_tool_result_carries_data_tool_call_id():
    """Le result porte data-tool-call-id (meme id que le call) pour l'appariement (b)."""
    message = {
        "role": "tool",
        "name": "Bash",
        "tool_call_id": "call_42",
        "content": "sortie de la commande",
    }

    html = message_view.render_message(message)

    assert 'data-tool-call-id="call_42"' in html
    assert 'class="tr' in html


def test_call_and_result_share_the_same_id():
    """Un call et son result exposent le MEME identifiant -> appariables."""
    call_msg = {
        "role": "assistant",
        "content": "",
        "tool_calls": [{"id": "abc", "name": "Read", "input": {"file_path": "/x"}}],
    }
    result_msg = {"role": "tool", "name": "Read", "tool_call_id": "abc", "content": "data"}

    call_html = message_view.render_message(call_msg)
    result_html = message_view.render_message(result_msg)

    assert 'data-tool-id="abc"' in call_html
    assert 'data-tool-call-id="abc"' in result_html


# --- T3 : suppression des etiquettes de role VOUS / ASSISTANT --------------


def test_user_message_has_no_role_pill():
    """T3 : le message user ne porte plus de pill de role (le role vient de la forme)."""
    message = {"role": "user", "content": "salut peux-tu maider"}

    html = message_view.render_message(message)

    # plus aucune pill de role
    assert 'class="role pui-eyebrow"' not in html
    assert ">vous</div>" not in html
    # le contenu reste rendu
    assert "salut peux-tu maider" in html


def test_assistant_message_has_no_role_pill():
    """T3 : le message assistant ne porte plus de pill de role."""
    message = {
        "role": "assistant",
        "content": "voici ma reponse",
        "tool_calls": [],
    }

    html = message_view.render_message(message)

    assert 'class="role pui-eyebrow"' not in html
    assert ">assistant</div>" not in html
    assert "voici ma reponse" in html


def test_thinking_eyebrow_kept_after_pill_removal():
    """T3 : l'eyebrow du bloc reflexion (meta utile) est CONSERVE apres retrait des pills de role."""
    message = {
        "role": "assistant",
        "content": "<thinking>\nje reflechis\n</thinking>\nreponse",
    }

    html = message_view.render_message(message)

    # eyebrow thinking garde, mais aucune pill de role
    assert 'pui-bubble__thinking-pill' in html
    assert 'class="role pui-eyebrow"' not in html


# --- Enforcement : les EnforcementWarning persistes sont rendus dans un bloc dedie -------


def test_enforcement_message_rendered_with_missing_tools():
    """Un message persiste role=enforcement rend un bloc dedie listant les outils manquants.

    Besoin user : voir "Enforcement: requesting Methodology, Snippet..." dans web_v2,
    reconstruit depuis session.json (et non un event live comme dans le REPL)."""
    message = {
        "role": "enforcement",
        "missing_tools": ["Methodology", "Snippet"],
        "turn": 3,
    }

    html = message_view.render_message(message)

    # bloc dedie, pas un bloc user
    assert "enforcement" in html
    assert 'pui-bubble--user' not in html
    assert 'class="block user' not in html
    # les deux outils manquants sont listes
    assert "Methodology" in html
    assert "Snippet" in html


def test_enforcement_message_single_tool():
    message = {"role": "enforcement", "missing_tools": ["Methodology"], "turn": 1}

    html = message_view.render_message(message)

    assert "enforcement" in html
    assert "Methodology" in html


def test_enforcement_message_without_missing_tools_does_not_crash():
    """Robustesse : missing_tools absent ne doit pas lever."""
    message = {"role": "enforcement", "turn": 1}

    html = message_view.render_message(message)

    assert "enforcement" in html
