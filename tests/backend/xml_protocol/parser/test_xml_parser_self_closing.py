# [desc] Tests that the XML parser tolerates self-closing <param .../> tags emitted by weaker models. [/desc]
"""Self-closing <param .../> tolerance.

Weaker models (e.g. deepseek-v4-flash) emit booleans as self-closing param tags
like `<param name="flag" value="false"/>`. The strict parser used to fail
`_find_param_close` on these, dropping the WHOLE batch as a single
`_XmlParseError` (observed regression: a Glob + Methodology batch was destroyed
together, triggering a wasted enforcement round-trip).
"""
from __future__ import annotations


def _parser():
    from bouzecode.backend.xml_tool_protocol import XmlToolStreamParser
    return XmlToolStreamParser()


def _feed(parser, chunk):
    items = parser.feed(chunk)
    completed = [item for item in items if isinstance(item, dict)]
    return completed


def test_self_closing_param_value_attribute_is_captured():
    p = _parser()
    xml = '<tool_use name="Glob" id="g1"><param name="pattern">**/*.py</param>' \
          '<param name="recurse" value="false"/></tool_use>'
    completed = _feed(p, xml)
    assert len(completed) == 1
    assert completed[0]["name"] == "Glob"
    assert completed[0]["input"] == {"pattern": "**/*.py", "recurse": "false"}


def test_self_closing_param_without_value_is_empty_string():
    p = _parser()
    xml = '<tool_use name="X" id="x1"><param name="flag"/></tool_use>'
    completed = _feed(p, xml)
    assert completed[0]["input"] == {"flag": ""}


def test_session_repro_self_closing_does_not_destroy_following_block():
    """Exact shape from session_112830: a Glob with a self-closing param
    followed by a Methodology block — both must parse, no _XmlParseError."""
    p = _parser()
    glob = ('<tool_use name="Glob" id="x5">'
            '<param name="pattern">**/.venv/**</param>'
            '<param name="path">C:\\proj\\app</param>'
            '<param name="ignore_gitignore" value="false"/></tool_use>')
    methodology = ('<tool_use name="Methodology" id="x6">'
                   '<param name="content">exploration en cours</param></tool_use>')
    completed = _feed(p, glob + "\n\n" + methodology)
    names = [c["name"] for c in completed]
    assert "_XmlParseError" not in names
    assert names == ["Glob", "Methodology"]
    assert completed[0]["input"]["ignore_gitignore"] == "false"
    assert completed[1]["input"]["content"] == "exploration en cours"


def test_self_closing_param_split_across_chunks():
    p = _parser()
    completed = _feed(p, '<tool_use name="Glob" id="g1"><param name="p">x</param><param name="r" value="tru')
    completed += _feed(p, 'e"/></tool_use>')
    assert len(completed) == 1
    assert completed[0]["input"] == {"p": "x", "r": "true"}
