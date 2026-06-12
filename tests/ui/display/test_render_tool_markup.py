# [desc] Tests that Rich Markdown tool_use markup neutralization preserves <param> tags verbatim in rendered output [/desc]
"""Bug A: Rich Markdown silently strips <param …> tags, collapsing a well-formed
tool call into an unreadable concatenated blob. _neutralize_tool_markup must
entity-escape the markup so it renders verbatim."""
from __future__ import annotations

import io

from rich.console import Console
from rich.markdown import Markdown

from bouzecode.ui.rendering import _neutralize_tool_markup, _make_renderable


def _render(text: str) -> str:
    buf = io.StringIO()
    Console(file=buf, width=200, force_terminal=False).print(Markdown(text))
    return buf.getvalue()


CALL = (
    '<tool_use name="Grep" id="t17_g1">'
    '<param name="pattern">stream|sse</param>'
    '<param name="path">C:\\x\\focus</param>'
    '</tool_use>'
)


def test_markdown_strips_param_tags_without_neutralizing():
    # Documents the underlying Rich behaviour the fix defends against.
    out = _render(CALL)
    assert "<param" not in out
    assert "stream|sseC:\\x\\focus" in out  # values collapsed together


def test_neutralized_markup_renders_param_tags_verbatim():
    out = _render(_neutralize_tool_markup(CALL))
    assert '<param name="pattern">stream|sse</param>' in out
    assert '<param name="path">C:\\x\\focus</param>' in out


def test_make_renderable_neutralizes_when_markdown():
    # Methodology-style text (has '[' so it goes through Markdown) carrying a call.
    text = f"Plan:\n[ ] run grep\n{CALL}"
    rendered = _make_renderable(text)
    assert isinstance(rendered, Markdown)
    assert "&lt;param" in rendered.markup


def test_plain_text_without_markdown_chars_is_untouched():
    # No markdown chars → returned as-is (printed literally, no stripping anyway).
    assert _make_renderable("just text") == "just text"
