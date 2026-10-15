# [desc] Le delta Methodology du tour est rendu visible dans la bulle assistant, hors du groupe d'outils replié. [/desc]
"""Dans web_v2, l'appel Methodology était enfoui dans « ▸ 2 outils · Methodology, Read ».
L'utilisateur doit voir le texte ajouté ce tour-ci, comme il voit la réflexion."""
from __future__ import annotations

from bouzecode.web_v2.services import message_view


def _assistant(tool_calls: list, content: str = "Je lis le fichier.") -> dict:
    return {"role": "assistant", "content": content, "tool_calls": tool_calls}


def _visible_part(html: str) -> str:
    """Ce qui est rendu AVANT le groupe d'outils replié."""
    return html.split('<details class="tools-group">', 1)[0]


def test_methodology_delta_is_shown_outside_the_collapsed_tools_group():
    html = message_view.render_message(_assistant([
        {"id": "m1", "name": "Methodology",
         "input": {"content": "- **Décision** : corriger `parse()`\n- Prochaine étape : relancer"}},
        {"id": "r1", "name": "Read", "input": {"file_path": "a.py"}},
    ]))
    visible = _visible_part(html)
    assert 'class="methodology' in visible
    assert "méthodologie" in visible
    assert "<strong>Décision</strong>" in visible
    assert "<code>parse()</code>" in visible
    assert "Prochaine étape : relancer" in visible
    # déplié par défaut : lisible sans clic
    assert "<details class=\"methodology pui-detail-thinking\" open>" in visible


def test_methodology_block_comes_after_thinking_and_text():
    html = message_view.render_message(_assistant(
        [{"id": "m1", "name": "Methodology", "input": {"content": "delta du tour"}}],
        content="<thinking>\nje pèse\n</thinking>\nTexte visible.",
    ))
    assert html.index("je pèse") < html.index("Texte visible.") < html.index("delta du tour")


def test_methodology_content_is_escaped():
    html = message_view.render_message(_assistant(
        [{"id": "m1", "name": "Methodology", "input": {"content": "<script>alert(1)</script>"}}]))
    assert "<script>" not in _visible_part(html)
    assert "&lt;script&gt;" in _visible_part(html)


def test_no_methodology_block_without_methodology_call():
    html = message_view.render_message(_assistant(
        [{"id": "r1", "name": "Read", "input": {"file_path": "a.py"}}]))
    assert 'class="methodology' not in html


def test_empty_methodology_content_renders_no_block():
    html = message_view.render_message(_assistant(
        [{"id": "m1", "name": "Methodology", "input": {"content": "  "}}]))
    assert 'class="methodology' not in html
