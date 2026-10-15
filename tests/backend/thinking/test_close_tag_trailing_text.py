# [desc] Tests de régression du parseur de streaming : fermeture `</thinking>` suivie de texte en colonne 0 [/desc]
"""Regression: `</thinking> trailing text` en col 0 doit fermer le bloc.

Symptome utilisateur: la balise fermante fuyait dans le texte visible
("</thinking> ou ool_calls>") parce que la fermeture n'etait acceptee que
si la balise etait SEULE sur sa ligne.
"""

from bouzecode.backend.agent.thinking_parser import ThinkingStreamParser


def _join(events, kind):
    return "".join(text for k, text in events if k == kind)


def test_close_tag_followed_by_text_closes_block():
    parser = ThinkingStreamParser()
    events = parser.feed(
        "<thinking>\n  je reflechis\n</thinking> ou autre chose"
    )
    events += parser.finalize()

    thinking = _join(events, "thinking")
    text = _join(events, "text")

    assert not parser.in_thinking
    assert "je reflechis" in thinking
    assert "</thinking>" not in thinking
    assert "</thinking>" not in text
    assert text == " ou autre chose"


def test_close_tag_split_across_two_chunks():
    parser = ThinkingStreamParser()
    events = parser.feed("<thinking>\n  je reflechis\n</thi")
    events += parser.feed("nking> suite visible")
    events += parser.finalize()

    thinking = _join(events, "thinking")
    text = _join(events, "text")

    assert not parser.in_thinking
    assert "</thinking>" not in thinking
    assert "</thinking>" not in text
    assert "</thi" not in text
    assert "je reflechis" in thinking
    assert text == " suite visible"


def test_close_tag_alone_on_line_still_closes():
    parser = ThinkingStreamParser()
    events = parser.feed("<thinking>\n  plan\n</thinking>\nreponse visible")
    events += parser.finalize()

    assert not parser.in_thinking
    assert _join(events, "thinking") == "\n  plan\n"
    assert _join(events, "text") == "\nreponse visible"


def test_mention_mid_line_does_not_close():
    parser = ThinkingStreamParser()
    events = parser.feed(
        "<thinking>\n  le parseur cherche </thinking> en colonne 0\n"
    )
    thinking = _join(events, "thinking")

    assert parser.in_thinking
    assert _join(events, "text") == ""
    events += parser.finalize()
    assert "</thinking>" in _join(events, "thinking")


def test_text_after_close_is_never_thinking():
    parser = ThinkingStreamParser()
    events = parser.feed("<thinking>\n  reflexion\n</thinking> Voici la reponse.\n")
    events += parser.feed("Deuxieme ligne.\n")
    events += parser.finalize()

    assert not parser.in_thinking
    thinking = _join(events, "thinking")
    assert "Voici la reponse." not in thinking
    assert "Deuxieme ligne." not in thinking
    assert _join(events, "text") == " Voici la reponse.\nDeuxieme ligne.\n"
    assert parser.full_thinking_text == "\n  reflexion\n"


def test_close_tag_with_trailing_text_in_finalize():
    parser = ThinkingStreamParser()
    events = parser.feed("<thinking>\n  fin de flux\n")
    events += parser.finalize()
    # nothing to close: unterminated block stays thinking
    assert "fin de flux" in _join(events, "thinking")

    parser2 = ThinkingStreamParser()
    events2 = parser2.feed("<thinking>\n  x\n</thinking> queue")
    events2 += parser2.finalize()
    assert _join(events2, "text") == " queue"
    assert not parser2.in_thinking
