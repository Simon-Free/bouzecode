# [desc] E2E tests for mock-API harness: real wire/SSE/parse/retry pipeline against a fake Anthropic server.
# <tool_use name="FinalAnswer" id="f1"><param name="answer">E2E tests for mock-API harness: real wire/SSE/parse/retry pipeline against a fake Anthropic server.</param></tool_use> [/desc]
"""mock_api mode: run the full real pipeline against a fake Anthropic HTTP/SSE server.

Unlike mock_llm (which patches the stream function), mock_api points the real client
at a fake server, so dispatch + get_tool_schemas + wire serialization + anthropic_stream
+ SSE parsing + the XML tool parser + retry all execute for real. We assert on the
recorded request bodies (the actual wire payload) and on the parsed conversation.
"""
from __future__ import annotations

from tests.e2e_harness import bouzecode

METH = '<tool_use name="Methodology" id="m1"><param name="content">ok</param></tool_use>'


def test_mock_api_runs_real_pipeline_and_records_wire_payload():
    result = bouzecode(["hi there"], mock_api=[f"Hello from the wire.\n{METH}"])
    assert "Hello from the wire." in result.last_reply
    assert result.recorded_requests, "the real client should have hit the mock API"
    body = result.recorded_requests[0]
    # The real wire payload built by messages_to_anthropic: a system + messages.
    assert "system" in body and "messages" in body
    # XML tool protocol: the tool docs ride in the system prompt (not a native `tools` field).
    assert "tools" not in body  # bouzecode uses XML-in-text tools, never native tool_use


def test_tool_use_split_across_sse_chunks_is_reassembled():
    """A <tool_use> tag split across text_delta chunks must be reassembled by the REAL
    XmlToolStreamParser — exactly the streaming-parser invariant the unit tests cover,
    now driven end to end from the wire."""
    bash = '<tool_use name="Bash" id="b1"><param name="command">echo hi</param></tool_use>'
    full = f"{METH}\n{bash}"
    # Split the response into many tiny chunks, cutting through the middle of tags.
    chunks = [full[i:i + 7] for i in range(0, len(full), 7)]
    result = bouzecode(
        ["run it"],
        mock_api=[{"chunks": chunks}, f"done.\n{METH}"],
    )
    # The reassembled Bash tool actually executed (its result is in the transcript).
    bash_results = [m for m in result.messages
                    if m.get("role") == "tool" and m.get("name") == "Bash"]
    assert bash_results, "the split-across-chunks Bash tool_use was parsed and run"


def test_server_error_then_success_is_retried():
    """The API returns 500 on the first hit, then a valid response — the REAL retry
    logic recovers and the conversation completes. (resilience, end to end)"""
    result = bouzecode(
        ["hi"],
        mock_api=[{"status": 500}, f"recovered.\n{METH}"],
    )
    assert "recovered." in result.last_reply
    # Two HTTP POSTs reached the server: the failed one and the retry.
    assert len(result.recorded_requests) >= 2


def test_thinking_streamed_via_sse_lands_in_transcript():
    """Thinking emitted as thinking_delta SSE events is parsed by the REAL pipeline and
    archived in the transcript (the <thinking> block), then stripped from later wire turns."""
    result = bouzecode(
        ["reason about it"],
        mock_api=[{"thinking": ["private reasoning here"], "text": f"the answer.\n{METH}"}],
    )
    asst = [m for m in result.messages if m.get("role") == "assistant"][0]
    assert "<thinking>" in asst["content"]
    assert "private reasoning here" in asst["content"]
