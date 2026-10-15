"""Orphan `</thinking>` (close tag with NO opening tag) must still be honoured.

Reported 2026-08-27: a model emitted its whole reflection as plain prose ending with
a `</thinking>` at column 0, without ever opening `<thinking>`. Both the batch cleaner
(`strip_thinking_tags`) and the streaming parser (`ThinkingStreamParser`) short-circuit
when no opening tag is present, so the reflection leaked into the visible answer AND the
literal `</thinking>` was rendered to the user.

Expected behaviour: a `</thinking>` at column 0 without a pending open acts as if the
block had been opened at the start of the segment.
"""

from bouzecode.backend.agent.thinking_parser import (
    ThinkingStreamParser,
    strip_thinking_tags,
)

# Verbatim-ish reproduction of the reported message: reflection, then a column-0 close
# tag, then real prose. Note the mid-line *mention* of the open tag in the trailing text.
USER_CASE = """Writer trouve : session.py L83-91 (_serialize-like dict). J'ajoute les 3 cles la.

Ensuite le service de lecture. Decisions deja notees ; j'ecris le fichier + son test dans ce batch.

</thinking> --> La, il manque un bloc <thinking> mal parse qui fait qu'on ne parse pas la reflexion..."""

# Same shape, but with NO occurrence of the opening tag at all: exercises the
# `if "<thinking>" not in content: return content` short-circuit.
NO_OPEN_MENTION = """Analyse du tour : le bug est dans le garde-fou d'entree.

</thinking> Voici la reponse finale."""


def test_strip_removes_reflection_before_orphan_close_tag():
    cleaned = strip_thinking_tags(USER_CASE)
    assert "</thinking>" not in cleaned, "the close tag must never reach the user"
    assert "Writer trouve" not in cleaned, "reflection must be stripped from the prose"
    assert "J'ajoute les 3 cles" not in cleaned
    assert "il manque un bloc" in cleaned, "prose after the close tag must survive"


def test_strip_handles_orphan_close_without_any_open_mention():
    cleaned = strip_thinking_tags(NO_OPEN_MENTION)
    assert "</thinking>" not in cleaned
    assert "Analyse du tour" not in cleaned
    assert cleaned.strip() == "Voici la reponse finale."


def test_stream_parser_classifies_text_before_orphan_close_as_thinking():
    parser = ThinkingStreamParser()
    events = parser.feed(NO_OPEN_MENTION)
    events += parser.feed("")

    kinds = {kind for kind, _ in events}
    assert "thinking" in kinds, f"expected a thinking event, got {events!r}"

    thinking = "".join(payload for kind, payload in events if kind == "thinking")
    text = "".join(payload for kind, payload in events if kind == "text")

    assert "Analyse du tour" in thinking
    assert "Analyse du tour" not in text
    assert "Voici la reponse finale." in text
    assert "</thinking>" not in text
    assert "</thinking>" not in thinking


def test_mid_line_close_tag_mention_is_not_a_close():
    """Non-regression: a *mention* of the tag mid-line must stay plain text."""
    content = "Le parser cherche un </thinking> en colonne 0 uniquement."
    assert strip_thinking_tags(content) == content

    parser = ThinkingStreamParser()
    events = parser.feed(content)
    assert all(kind == "text" for kind, _ in events), events
