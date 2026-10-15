# [desc] Les attributs d'ordonnancement doivent sortir du parser TYPES (depends_on = vraie liste).
"""Le TUI affichait `depends_on="["lp1"]"` : une liste re-serialisee en chaine.

Le parser conservait volontairement la forme textuelle parce que le DAG la
re-decodait en aval (dag._coerce_list). Resultat : tout ce qui regarde
`tool_call["input"]` avant l'execution (rendu terminal, replay, logs) voit une
chaine la ou le protocole documente un tableau JSON.
"""

from bouzecode.backend.xml_tool_protocol.parser import XmlToolStreamParser

LT = chr(60)
GT = chr(62)


def _one_call(attrs: str) -> dict:
    parser = XmlToolStreamParser()
    text = (
        LT + "tool_calls" + GT
        + LT + 'tool_use name="Bash" id="b1" ' + attrs + GT
        + LT + 'param name="command"' + GT + "echo hi" + LT + "/param" + GT
        + LT + "/tool_use" + GT
        + LT + "/tool_calls" + GT
    )
    items = list(parser.feed(text)) + list(parser.finalize())
    calls = [item for item in items if isinstance(item, dict)]
    assert len(calls) == 1, f"attendu 1 appel, recu {items!r}"
    return calls[0]


def test_bare_json_array_becomes_a_real_list():
    call = _one_call('depends_on=["w1","w2"]')
    assert call["input"]["depends_on"] == ["w1", "w2"]


def test_quoted_json_array_becomes_a_real_list():
    call = _one_call('depends_on="["w1"]"')
    assert call["input"]["depends_on"] == ["w1"]


def test_alias_stays_a_plain_string():
    call = _one_call('tool_call_alias="w1"')
    assert call["input"]["tool_call_alias"] == "w1"


def test_unparsable_array_is_left_readable_as_text():
    """Un tableau casse ne doit pas faire perdre l'appel : on garde la chaine."""
    call = _one_call('depends_on="[w1"')
    assert isinstance(call["input"]["depends_on"], str)
