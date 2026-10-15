# [desc] End-to-end streaming XML-parser coverage via mock_api: the REAL parser handles wire-fragmented tool_use, CDATA, fenced/thinking shielding, and truncation. [/desc]
"""The pure XmlToolStreamParser invariants live (fast) in xml_protocol/parser/*; this
file proves the SAME behaviours hold END TO END — the real anthropic_stream + parser
fed by genuine SSE text_deltas from the wire (via mock_api), not a direct .feed().
"""
from __future__ import annotations

import sys

import pytest

from tests.e2e_harness import bouzecode

# The mock_api harness runs a threaded werkzeug server + httpx streaming; that
# combination dead-locks intermittently on Windows (the reader thread hangs on a
# socket that never EOFs), freezing the whole worker. The parser invariants are
# also covered (fast, hermetically) by xml_protocol/parser/*. Runs on Linux CI.
pytestmark = pytest.mark.skipif(
    sys.platform == "win32",
    reason="mock_api e2e hangs on Windows (threaded werkzeug + httpx streaming)",
)

METH = '<tool_use name="Methodology" id="m1"><param name="content">ok</param></tool_use>'
# A Methodology-only batch never closes the session (it earns a continue-nudge): a
# script whose first reply carries only Methodology needs this plain closing reply.
CLOSE = "C'est fait."


def _bash_results(result):
    return [m for m in result.messages if m.get("role") == "tool" and m.get("name") == "Bash"]


def _chunks(s: str, n: int = 7) -> list[str]:
    return [s[i:i + n] for i in range(0, len(s), n)]


def test_tool_use_split_across_sse_chunks_executes():
    """A <tool_use> fragmented into 7-char SSE deltas is reassembled by the real parser."""
    bash = '<tool_use name="Bash" id="b1"><param name="command">echo hi</param></tool_use>'
    result = bouzecode(["run"], mock_api=[{"chunks": _chunks(f"{METH}\n{bash}")}, "C'est fait."])
    assert _bash_results(result)


def test_gateway_swallowed_closing_wrapper_head_does_not_leak():
    """The gateway ate the delta holding the start of the closing wrapper tag.

    Real incident (session 46cf0a617b4c): the cut marker was applied across two
    SSE deltas, the delta carrying the first characters of the closing wrapper
    tag was dropped server-side, and the client received the remainder alone.
    Having never seen the tag start, the parser could not hold it back and the
    leftovers surfaced as visible prose in 5 assistant messages.
    """
    LT, GT = chr(60), chr(62)
    bash = (f'{LT}tool_use name="Bash" id="b1"{GT}'
            f'{LT}param name="command"{GT}echo hi{LT}/param{GT}{LT}/tool_use{GT}')
    close = f'{LT}/tool_calls{GT}'
    batch = f'{LT}tool_calls{GT}{METH}\n{bash}{close}'
    head, orphan = batch[:-len(close)], close[3:]
    result = bouzecode(["run"], mock_api=[{"chunks": [*_chunks(head), orphan]}, "C'est fait."])
    assert _bash_results(result)
    said = "".join(m.get("content") or "" for m in result.messages if m.get("role") == "assistant")
    # The transcript keeps the model's real wrapper tags; only an orphan TAIL may not survive.
    leftover = said.replace(f"{LT}tool_calls{GT}", "").replace(close, "")
    assert "ool_calls" not in leftover


def test_cdata_special_chars_split_across_chunks_round_trips(tmp_path):
    """A CDATA param value with <, &, > split across chunks reaches the tool input intact."""
    f = tmp_path / "temp_cdata.py"
    write = (f'<tool_use name="Write" id="w1"><param name="file_path">{f}</param>'
             f'<param name="content"><![CDATA[x = 1 < 2 && y > 0]]></param></tool_use>')
    result = bouzecode(["write"], mock_api=[{"chunks": _chunks(f"{METH}\n{write}")}, "C'est fait."])
    assert f.exists()
    assert "1 < 2 && y > 0" in f.read_text(encoding="utf-8")


def test_tool_use_inside_fenced_code_block_is_not_executed():
    """A <tool_use> written inside a ``` code fence is prose, not a call — not executed."""
    text = ("Example:\n```\n"
            '<tool_use name="Bash" id="b1"><param name="command">echo SHOULD_NOT_RUN</param></tool_use>\n'
            f"```\nThat was an example.\n{METH}")
    result = bouzecode(["explain"], mock_api=[text, CLOSE])
    assert not _bash_results(result)


def test_thinking_block_shields_inner_tool_use():
    """A <tool_use> inside a line-start <thinking> block is shielded — not executed."""
    text = ("<thinking>\n"
            '<tool_use name="Bash" id="b1"><param name="command">echo SHOULD_NOT_RUN</param></tool_use>\n'
            f"</thinking>\nDone reasoning.\n{METH}")
    result = bouzecode(["think"], mock_api=[text, CLOSE])
    assert not _bash_results(result)


def test_incomplete_tool_use_at_stream_cut_is_handled_gracefully():
    """The stream is cut mid-<tool_use> (never closed): the loop doesn't crash, the
    incomplete call is surfaced/ignored, and the conversation continues."""
    partial = f'{METH}\n<tool_use name="Bash" id="b1"><param name="command">echo incompl'
    result = bouzecode(
        ["run"],
        mock_api=[{"chunks": _chunks(partial), "truncate_after": 1000}, "recovered."],
    )
    # No crash; the conversation produced a final reply and the incomplete Bash never ran.
    assert result.last_reply
    assert not _bash_results(result)
