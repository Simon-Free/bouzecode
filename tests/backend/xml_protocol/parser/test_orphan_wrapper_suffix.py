"""Le gateway ampute le debut de la balise fermante du wrapper.

Cas reel (session 46cf0a617b4c, 5 messages) : la coupure demandee a l API est
appliquee a cheval sur deux deltas SSE. Le delta portant les premiers
caracteres de la balise fermante est supprime cote serveur, et le client
recoit un residu orphelin en tete du delta suivant. Le parser, qui n a jamais
vu le debut du tag, ne peut pas le retenir : le residu fuit en texte visible.
"""

from bouzecode.backend.xml_tool_protocol.parser import XmlToolStreamParser

LT = chr(60)
GT = chr(62)
CLOSE = LT + "/tool_calls" + GT


def _batch() -> str:
    return (
        LT + "tool_calls" + GT
        + LT + 'tool_use name="Methodology" id="m1"' + GT
        + LT + 'param name="content"' + GT + "hello" + LT + "/param" + GT
        + LT + "/tool_use" + GT
        + CLOSE
    )


def _feed(chunks):
    parser = XmlToolStreamParser()
    items = []
    for chunk in chunks:
        items.extend(parser.feed(chunk))
    items.extend(parser.finalize())
    return items


def test_orphan_closing_suffix_never_reaches_visible_text():
    batch = _batch()
    head = batch[: -len(CLOSE)]
    orphan = CLOSE[3:]

    items = _feed([head, orphan])

    text = "".join(item for item in items if isinstance(item, str))
    tools = [item for item in items if isinstance(item, dict)]

    assert "ool_calls" not in text, f"residu de wrapper visible: {text!r}"
    assert text.strip() == ""
    assert [tool["name"] for tool in tools] == ["Methodology"]


def test_intact_closing_tag_still_works():
    items = _feed([_batch()])
    text = "".join(item for item in items if isinstance(item, str))
    tools = [item for item in items if isinstance(item, dict)]
    assert text.strip() == ""
    assert [tool["name"] for tool in tools] == ["Methodology"]


def test_orphan_suffix_preceded_by_a_newline_is_absorbed():
    """Le residu arrive seul sur sa ligne : le TUI affichait `ool_calls>` en clair."""
    batch = _batch()
    head = batch[: -len(CLOSE)]
    orphan = "\n" + CLOSE[3:]

    items = _feed([head, orphan])

    text = "".join(item for item in items if isinstance(item, str))
    tools = [item for item in items if isinstance(item, dict)]

    assert "ool_calls" not in text, f"residu de wrapper visible: {text!r}"
    assert [tool["name"] for tool in tools] == ["Methodology"]


def test_orphan_suffix_after_prose_in_the_same_delta_is_absorbed():
    """Le delta forwarde porte la fin de la prose PUIS le residu de balise."""
    batch = _batch()
    head = batch[: -len(CLOSE)]
    orphan = "voila.\n" + CLOSE[3:]

    items = _feed([head, orphan])

    text = "".join(item for item in items if isinstance(item, str))

    assert "voila." in text, f"prose perdue: {text!r}"
    assert "ool_calls" not in text, f"residu de wrapper visible: {text!r}"


def test_prose_starting_like_a_suffix_is_kept():
    items = _feed(["ool_calls are fine in prose" + GT])
    text = "".join(item for item in items if isinstance(item, str))
    assert "ool_calls are fine in prose" in text
