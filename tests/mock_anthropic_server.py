# [desc] Mock Anthropic SSE streaming API server for e2e tests: configurable responses, records requests. [/desc]
"""Mock Anthropic /v1/messages API returning configurable SSE, recording requests.

A response item is either:
  - a str: streamed as a single text_delta (back-compat), or
  - a dict with any of:
      "text":    str  — convenience, becomes one text chunk if "chunks" absent
      "chunks":  list[str] — text_deltas emitted one per item (controls chunk boundaries,
                  e.g. splitting a <tool_use> tag mid-stream so the REAL XmlToolStreamParser
                  must reassemble it)
      "thinking": list[str] — emitted as a thinking content block (thinking_delta events)
      "stop_reason": str (default "end_turn"; use "max_tokens" for truncation tests)
      "status":  int — return this HTTP status with an error body instead of SSE (e.g. 429/500
                  for retry/resilience tests). The Anthropic SDK retries, hitting the next item.
      "truncate_after": int — emit only the first N text chunks then end the stream WITHOUT
                  content_block_stop/message_stop (simulates a dropped/cut connection)
      "raw_sse": str — emit this literal SSE body verbatim (for malformed-event tests)

Mock the API (this) when you need the real dispatch/schema/wire/SSE/retry pipeline to run;
mock the LLM (tests.fake_llm.MockLLM via the harness) for fast loop-behaviour tests.
"""
import json
import socket
import threading

from flask import Flask, request, Response


def _free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _render_sse(item: dict, call_index: int):
    """Yield the SSE body for one response item."""
    if item.get("raw_sse") is not None:
        yield item["raw_sse"]
        return

    thinking = item.get("thinking") or []
    chunks = item.get("chunks")
    if chunks is None:
        text = item.get("text", "")
        chunks = [text] if text else []
    truncate_after = item.get("truncate_after")
    stop_reason = item.get("stop_reason", "end_turn")

    yield _sse("message_start", {
        "type": "message_start",
        "message": {
            "id": f"msg_test_{call_index}", "type": "message", "role": "assistant",
            "content": [], "model": "claude-sonnet-4-20250514",
            "stop_reason": None, "stop_sequence": None,
            "usage": {"input_tokens": 100, "output_tokens": 0},
        },
    })

    block_idx = 0
    if thinking:
        yield _sse("content_block_start", {
            "type": "content_block_start", "index": block_idx,
            "content_block": {"type": "thinking", "thinking": ""},
        })
        for t in thinking:
            yield _sse("content_block_delta", {
                "type": "content_block_delta", "index": block_idx,
                "delta": {"type": "thinking_delta", "thinking": t},
            })
        yield _sse("content_block_stop", {"type": "content_block_stop", "index": block_idx})
        block_idx += 1

    yield _sse("content_block_start", {
        "type": "content_block_start", "index": block_idx,
        "content_block": {"type": "text", "text": ""},
    })
    for i, c in enumerate(chunks):
        if truncate_after is not None and i >= truncate_after:
            return  # drop the stream mid-flight: no content_block_stop / message_stop
        yield _sse("content_block_delta", {
            "type": "content_block_delta", "index": block_idx,
            "delta": {"type": "text_delta", "text": c},
        })
    if truncate_after is not None:
        return

    yield _sse("content_block_stop", {"type": "content_block_stop", "index": block_idx})
    yield _sse("message_delta", {
        "type": "message_delta",
        "delta": {"stop_reason": stop_reason, "stop_sequence": None},
        "usage": {"output_tokens": sum(len(c) for c in chunks) // 4},
    })
    yield "event: message_stop\ndata: {\"type\":\"message_stop\"}\n\n"


def create_mock_anthropic_app(responses: list):
    """Flask app mimicking Anthropic's /v1/messages. `responses` items: str or dict (see module doc)."""
    app = Flask(__name__)
    app.recorded_calls = []
    app.call_index = 0

    @app.route("/v1/messages", methods=["POST"])
    def messages():
        app.recorded_calls.append(request.get_json())
        if app.call_index >= len(responses):
            return {"type": "error", "error": {"type": "overloaded_error",
                    "message": "no more responses configured"}}, 500
        item = responses[app.call_index]
        app.call_index += 1
        if isinstance(item, str):
            item = {"text": item}
        status = item.get("status")
        if status:
            return {"type": "error", "error": {"type": "api_error",
                    "message": f"mock status {status}"}}, status
        return Response(_render_sse(item, app.call_index), mimetype="text/event-stream")

    @app.route("/recorded_calls", methods=["GET"])
    def get_recorded_calls():
        return json.dumps(app.recorded_calls)

    return app


def start_mock_anthropic(responses: list) -> tuple[str, Flask]:
    """Start the mock server in a daemon thread. Returns (base_url, app). app.recorded_calls
    holds the real request bodies the client sent."""
    app = create_mock_anthropic_app(responses)
    port = _free_port()
    thread = threading.Thread(
        target=app.run,
        kwargs={"host": "127.0.0.1", "port": port, "use_reloader": False, "threaded": True},
        daemon=True,
    )
    thread.start()
    import time
    for _ in range(50):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                break
        except OSError:
            time.sleep(0.1)
    return f"http://127.0.0.1:{port}", app
