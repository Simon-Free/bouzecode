"""User-facing rendering of an orphan `</thinking>` (close tag with no opening tag).

Reported 2026-08-27: the reflection leaked into the visible bubble AND the literal
`</thinking>` was displayed. This test drives the real entry point used by the web UI,
`message_view.render_message()`, on an assistant message shaped like the reported one.
"""

from bouzecode.web_v2.services import message_view

ORPHAN_MESSAGE = """Writer trouve : session.py L83-91 (_serialize-like dict).

Ensuite le service de lecture ; j'ecris le fichier + son test dans ce batch.

</thinking> --> La, il manque un bloc mal parse."""


def _render(content: str) -> str:
    return message_view.render_message(
        {"role": "assistant", "content": content, "tool_calls": []}
    )


def test_orphan_close_tag_is_rendered_as_a_thinking_block():
    html_out = _render(ORPHAN_MESSAGE)

    # The reflection is folded into the thinking pill, not shown as prose.
    assert "thinking" in html_out, html_out
    assert "réflexion" in html_out, html_out
    assert "Writer trouve" in html_out, "reflection must still be readable in the pill"


def test_orphan_close_tag_never_leaks_to_the_user():
    html_out = _render(ORPHAN_MESSAGE)

    assert "&lt;/thinking&gt;" not in html_out, "escaped close tag leaked into the bubble"
    assert "</thinking>" not in html_out, "raw close tag leaked into the bubble"


def test_prose_after_the_orphan_close_tag_survives():
    html_out = _render(ORPHAN_MESSAGE)
    assert "il manque un bloc mal parse." in html_out


def test_paired_thinking_block_still_renders(capsys=None):
    """Non-regression: a well-formed block keeps working."""
    html_out = _render("<thinking>\n  je reflechis\n</thinking>\nVoici la reponse.")
    assert "réflexion" in html_out
    assert "je reflechis" in html_out
    assert "Voici la reponse." in html_out
    assert "&lt;thinking&gt;" not in html_out
