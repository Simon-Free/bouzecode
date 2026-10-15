# [desc] Regression tests: the parser must accept the batch closing tag quoted inside a param and only flag batch_closed at top level [/desc]
"""Regression: the model must be able to QUOTE the protocol's own closing tag.

The closing tag used to be sent to the API as a stop sequence, so generation was
cut wherever the sequence appeared -- including inside a <param> holding a test,
a doc or a regex about the XML protocol. The client now decides when the batch is
over, which requires the parser to tell a real top-level close from a quotation.

The literal tag is never typed here: it is imported, so this very file cannot be
truncated by the failure mode it covers.
"""
from bouzecode.backend.xml_tool_protocol import (
    TOOL_CALLS_CLOSE,
    TOOL_CALLS_OPEN,
    XmlToolStreamParser,
)


def _calls(items):
    return [it for it in items if isinstance(it, dict)]


def test_param_may_quote_the_batch_closing_tag_in_one_chunk():
    quoted = f"a batch ends on {TOOL_CALLS_CLOSE} exactly"
    stream = (
        TOOL_CALLS_OPEN
        + '<tool_use name="Write" id="w1"><param name="content">'
        + quoted
        + "</param></tool_use>"
        + TOOL_CALLS_CLOSE
    )
    parser = XmlToolStreamParser()
    calls = _calls(parser.feed(stream))
    assert len(calls) == 1, calls
    assert calls[0]["name"] == "Write"
    assert calls[0]["input"]["content"] == quoted


def test_param_may_quote_the_batch_closing_tag_inside_cdata():
    quoted = f"regex: {TOOL_CALLS_CLOSE}"
    stream = (
        TOOL_CALLS_OPEN
        + '<tool_use name="Write" id="w1"><param name="content"><![CDATA['
        + quoted
        + "]]" + ">"
        + "</param></tool_use>"
        + TOOL_CALLS_CLOSE
    )
    parser = XmlToolStreamParser()
    calls = _calls(parser.feed(stream))
    assert len(calls) == 1, calls
    assert calls[0]["input"]["content"] == quoted


def test_batch_closed_flag_only_fires_at_top_level():
    parser = XmlToolStreamParser()
    assert parser.batch_closed is False
    parser.feed(TOOL_CALLS_OPEN + '<tool_use name="Write" id="w1">')
    parser.feed('<param name="content">quoting ')
    parser.feed(f"{TOOL_CALLS_CLOSE} in the middle of a value")
    assert parser.batch_closed is False, "a quotation inside a param is not a close"
    calls = _calls(parser.feed("</param></tool_use>" + TOOL_CALLS_CLOSE))
    assert parser.batch_closed is True
    assert len(calls) == 1, calls
    assert calls[0]["input"]["content"] == (
        f"quoting {TOOL_CALLS_CLOSE} in the middle of a value"
    )


def test_plain_prose_never_flags_a_closed_batch():
    parser = XmlToolStreamParser()
    parser.feed("Just some prose, no tool call at all.\n")
    assert parser.batch_closed is False
