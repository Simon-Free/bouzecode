# [desc] The three accepted spellings of depends_on/tool_call_alias, and the rule that a nameless <tool_use> is prose, never a call. [/desc]
"""Two behaviours measured on real sessions (docs/investigations/xml_tool_call_failures.md).

1. The model writes its scheduling attributes three different ways. All three must
   reach the tool, because all three appear in production: it reads
   `<param name="depends_on">` in its own replayed history, sees `name="x"` quoting
   everywhere else, and improvises `depends_on="["w1"]"` — the single most frequent
   XML failure (50 % of the errors of the last three weeks).
2. A `<tool_use>` that names no tool is the model TALKING about the protocol, usually
   between backticks. It must produce no call and no error: an error here is a fake
   tool call the executor answers, costing a full API round-trip for nothing.
"""
from __future__ import annotations

from bouzecode.backend.xml_tool_protocol import XmlToolStreamParser, serialize_tool_call

# The exact payload that died in production, byte for byte.
QUOTED_BRACKETS = (
    '<tool_use name="Bash" id="b1" depends_on="["w1"]">'
    '<param name="command">echo hi</param></tool_use>'
)


def _run(chunks):
    """Feed the chunks then finalize; return (visible_text, tool_calls)."""
    parser = XmlToolStreamParser()
    items = []
    for chunk in chunks:
        items += parser.feed(chunk)
    items += parser.finalize()
    visible = "".join(item for item in items if isinstance(item, str))
    calls = [item for item in items if isinstance(item, dict)]
    return visible, calls


def _in_chunks(text: str, size: int) -> list[str]:
    return [text[i:i + size] for i in range(0, len(text), size)]


class TestSchedulingAttributesAreAccepted:
    """Whichever way the model spells depends_on, the tool it names must run."""

    def test_brackets_inside_quotes_still_call_bash(self):
        """`depends_on="["w1"]"` — the improvised form that used to kill the batch."""
        _, calls = _run([QUOTED_BRACKETS])
        assert [c["name"] for c in calls] == ["Bash"]
        assert calls[0]["id"] == "b1"
        assert calls[0]["input"]["command"] == "echo hi"
        assert calls[0]["input"]["depends_on"] == '["w1"]'

    def test_brackets_inside_quotes_survive_a_cut_in_the_middle_of_the_attribute(self):
        """The stream splits wherever it likes, including inside `depends_on="["w1"]"`."""
        for size in (1, 3, 7, 13, 40):
            _, calls = _run(_in_chunks(QUOTED_BRACKETS, size))
            assert [c["name"] for c in calls] == ["Bash"], f"chunk size {size}"
            assert calls[0]["input"]["depends_on"] == '["w1"]'

    def test_bare_brackets_still_call_bash(self):
        """`depends_on=["w1"]` — the form the system prompt teaches. No regression."""
        _, calls = _run([
            '<tool_use name="Bash" id="b1" tool_call_alias="b1" depends_on=["w1"]>'
            '<param name="command">echo hi</param></tool_use>'
        ])
        assert [c["name"] for c in calls] == ["Bash"]
        assert calls[0]["input"]["depends_on"] == '["w1"]'
        assert calls[0]["input"]["tool_call_alias"] == "b1"

    def test_the_param_form_the_serializer_emits_round_trips(self):
        """Replayed history comes back as `<param name="depends_on">["w1"]</param>`."""
        xml = serialize_tool_call({
            "id": "b1",
            "name": "Bash",
            "input": {"command": "echo hi", "depends_on": ["w1"]},
        })
        _, calls = _run([xml])
        assert [c["name"] for c in calls] == ["Bash"]
        assert calls[0]["input"] == {"command": "echo hi", "depends_on": '["w1"]'}

    def test_an_ordinary_quoted_value_that_looks_like_a_list_is_untouched(self):
        """Widening the attribute grammar must not change any other attribute."""
        _, calls = _run([
            '<tool_use name="Snippet" id="s1" ranges="[[1,50]]">'
            '<param name="file_path">a.py</param></tool_use>'
        ])
        assert calls[0]["input"]["file_path"] == "a.py"
        assert calls[0]["id"] == "s1"


class TestProseIsNotACall:
    """The model quoting the protocol must cost nothing at all."""

    def test_a_bare_tool_use_between_backticks_produces_no_call_and_no_error(self):
        text = (
            "The parser confuses a `<tool_use>` written in free text with a real call.\n"
            "Here it is again, closed: <tool_use></tool_use> — still only prose."
        )
        visible, calls = _run([text])
        assert calls == []
        assert "<tool_use></tool_use>" in visible

    def test_a_bare_tool_use_left_unclosed_by_the_stream_produces_no_call(self):
        """Prose cut mid-sentence is still prose: nothing to re-emit, nothing to report."""
        _, calls = _run(["I was about to write <tool_use> when the stream ended"])
        assert calls == []

    def test_prose_does_not_shadow_a_real_call_in_the_same_response(self):
        _, calls = _run([
            "A nameless <tool_use></tool_use> is not a call.\n"
            '<tool_use name="Bash" id="b1"><param name="command">echo hi</param></tool_use>'
        ])
        assert [c["name"] for c in calls] == ["Bash"]

    def test_a_call_that_lost_only_its_name_is_still_reported(self):
        """Params without a name is a genuine call gone wrong — it must NOT vanish."""
        _, calls = _run([
            '<tool_use><param name="command">rm -rf /tmp/x</param></tool_use>'
        ])
        assert [c["name"] for c in calls] == ["_XmlParseError"]
        assert "name" in calls[0]["input"]["_error"]


class TestTruncatedStreamsStayErrors:
    """A cut payload must never be completed by guesswork."""

    def test_a_write_cut_inside_its_content_errors_and_writes_nothing(self):
        _, calls = _run([
            '<tool_use name="Write" id="w1"><param name="file_path">a.py</param>'
            '<param name="content">def main():\n    hal'
        ])
        assert [c["name"] for c in calls] == ["_XmlParseError"]
        assert "content" in calls[0]["input"]["_error"]

    def test_a_bash_cut_inside_its_command_errors_instead_of_running_half_of_it(self):
        _, calls = _run([
            '<tool_use name="Bash" id="b1"><param name="command">rm -rf /tmp/build && ec'
        ])
        assert [c["name"] for c in calls] == ["_XmlParseError"]
        assert "b1" in calls[0]["input"]["_error"]
