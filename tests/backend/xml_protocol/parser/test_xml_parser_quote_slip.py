"""A `"> ` typed instead of `</param>` must not cost the whole tool-call batch.

Real session 2026-07-27: a manager emitted three tool calls; the first closed a
param value like an attribute (`...AZURE_"><param name=`). The strict parser
could no longer find any closing tag, so ALL THREE calls were dropped and the
agent lost a full turn. The parser must now salvage what is well formed and
point at what is actually broken.
"""
from __future__ import annotations

import logging

PARSER_LOGGER = "bouzecode.backend.xml_tool_protocol.parser"

# Verbatim source of the failing session, byte for byte.
BROKEN_BATCH = (
    '<tool_use name="Grep" id="g2"><param name="pattern">azure|parquet|BlobService'
    '|to_parquet|read_parquet|AZURE_"><param name="output_mode">files_with_matches'
    '</param><param name="case_insensitive">true</param></tool_use>\n'
    '<tool_use name="Grep" id="g3"><param name="pattern">is_staff|is_superuser'
    '|staff_member_required|UserPassesTestMixin|admin_required"><param name="path">'
    'src/apps</param><param name="output_mode">files_with_matches</param></tool_use>\n'
    '<tool_use name="Read" id="r1"><param name="file_path'
)


def _parser():
    from bouzecode.backend.xml_tool_protocol import XmlToolStreamParser
    return XmlToolStreamParser()


def _run(chunks):
    """Feed the chunks then finalize, returning (parser, tool_calls)."""
    p = _parser()
    calls = []
    for chunk in chunks:
        calls += [item for item in p.feed(chunk) if isinstance(item, dict)]
    calls += p.finalize()
    return p, calls


class TestRealSessionBatch:
    """The exact stream that died in production."""

    def test_the_two_greps_are_recovered_and_only_the_read_is_reported_broken(self):
        _, calls = _run([BROKEN_BATCH])
        assert [c["name"] for c in calls] == ["Grep", "Grep", "_XmlParseError"]

        g2, g3 = calls[0], calls[1]
        assert g2["id"] == "g2"
        assert g2["input"] == {
            "pattern": "azure|parquet|BlobService|to_parquet|read_parquet|AZURE_",
            "output_mode": "files_with_matches",
            "case_insensitive": "true",
        }
        assert g3["id"] == "g3"
        assert g3["input"] == {
            "pattern": "is_staff|is_superuser|staff_member_required"
            "|UserPassesTestMixin|admin_required",
            "path": "src/apps",
            "output_mode": "files_with_matches",
        }

    def test_the_error_names_the_tool_and_the_param_at_fault(self):
        _, calls = _run([BROKEN_BATCH])
        error = calls[-1]["input"]["_error"]
        assert "unclosed" in error.lower()
        assert 'name="Read"' in error
        assert 'id="r1"' in error
        assert "file_path" in error

    def test_same_result_when_the_batch_is_cut_across_chunks(self):
        chunks = [BROKEN_BATCH[i:i + 13] for i in range(0, len(BROKEN_BATCH), 13)]
        _, calls = _run(chunks)
        assert [c["name"] for c in calls] == ["Grep", "Grep", "_XmlParseError"]
        assert calls[0]["input"]["output_mode"] == "files_with_matches"

    def test_the_repair_is_traced_not_silent(self, caplog):
        with caplog.at_level(logging.WARNING, logger=PARSER_LOGGER):
            p, _ = _run([BROKEN_BATCH])
        assert len(p.recovered_slips) == 2
        assert all("pattern" in note for note in p.recovered_slips)
        assert "auto-recovery" in caplog.text


class TestMissingToolClose:
    """A forgotten </tool_use> only loses the call that forgot it."""

    def test_first_call_survives_when_the_second_opens_too_early(self):
        stream = (
            '<tool_use name="Grep" id="g1"><param name="pattern">x</param>\n'
            '<tool_use name="Grep" id="g2"><param name="pattern">y</param>'
        )
        p, calls = _run([stream])
        assert [c["name"] for c in calls] == ["Grep", "_XmlParseError"]
        assert calls[0]["id"] == "g1"
        assert calls[0]["input"] == {"pattern": "x"}
        assert 'id="g2"' in calls[1]["input"]["_error"]
        assert p.recovered_slips


class TestNominalStreamsUntouched:
    """Well-formed XML must go through exactly as before, with no repair."""

    def test_two_well_formed_calls_parse_at_feed_time(self):
        stream = (
            '<tool_use name="Methodology" id="m1"><param name="content">go</param>'
            '</tool_use>\n'
            '<tool_use name="Read" id="r1"><param name="file_path">a.py</param>'
            '</tool_use>'
        )
        p, calls = _run([stream])
        assert [c["name"] for c in calls] == ["Methodology", "Read"]
        assert calls[1]["input"]["file_path"] == "a.py"
        assert p.recovered_slips == []

    def test_cdata_value_with_angles_and_ampersand(self):
        stream = (
            '<tool_use name="Write" id="w1"><param name="file_path">t.html</param>'
            '<param name="content"><![CDATA[<a href="x">a & b</a>]]></param>'
            '</tool_use>'
        )
        p, calls = _run([stream])
        assert len(calls) == 1
        assert calls[0]["input"]["content"] == '<a href="x">a & b</a>'
        assert p.recovered_slips == []

    def test_bare_value_with_angles_and_ampersand(self):
        stream = (
            '<tool_use name="Bash" id="b1">'
            '<param name="command">echo "a & b" > out.txt && test 1 < 2</param>'
            '</tool_use>'
        )
        p, calls = _run([stream])
        assert len(calls) == 1
        assert calls[0]["input"]["command"] == 'echo "a & b" > out.txt && test 1 < 2'
        assert p.recovered_slips == []

    def test_quote_then_angle_not_followed_by_framing_is_left_alone(self):
        """`"> ` inside a value is only a slip when protocol framing follows it."""
        stream = (
            '<tool_use name="Bash" id="b1">'
            '<param name="command">grep "foo"> results.txt</param>'
            '</tool_use>'
        )
        p, calls = _run([stream])
        assert calls[0]["input"]["command"] == 'grep "foo"> results.txt'
        assert p.recovered_slips == []


class TestRecoveryStaysConservative:
    """Recovery must never invent a tool call out of a value's content."""

    def test_a_tool_use_example_inside_a_truncated_value_is_not_executed(self):
        """A truncated Write whose content shows example XML: no Bash must run."""
        stream = (
            '<tool_use name="Write" id="w1"><param name="content">Example:\n'
            '<tool_use name="Bash" id="b9"><param name="command">rm -rf /</param>'
            '</tool_use>\n'
        )
        _, calls = _run([stream])
        assert [c["name"] for c in calls] == ["_XmlParseError"]
        error = calls[0]["input"]["_error"]
        assert 'name="Write"' in error
        assert "content" in error

    def test_cdata_shields_a_value_that_literally_contains_the_slip(self):
        """CDATA is the escape hatch for a value that really holds `"><param name=`."""
        stream = (
            '<tool_use name="Write" id="w1"><param name="file_path">doc.md</param>'
            '<param name="content"><![CDATA[bad: value"><param name="next">]]></param>'
            '</tool_use>'
        )
        p, calls = _run([stream])
        assert len(calls) == 1
        assert calls[0]["input"]["content"] == 'bad: value"><param name="next">'
        assert p.recovered_slips == []
