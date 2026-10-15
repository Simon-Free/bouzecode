"""The usage block arrives AFTER the tool-call batch closes — don't hang up on it.

On an OpenAI-compatible endpoint (OpenRouter, or the internal LLM gateway serving claude-* through
a LiteLLM pass-through) the `usage` object is emitted in the LAST chunk, once every
`choices` delta has been sent. bouzecode closes its XML batch on `</tool_calls>` and used
to `break` out of the SSE loop right there, so that final chunk was never read: every
turn that ended on a tool batch reported 0 input/0 output tokens, and the status line
showed "+0 in · +0 out" for a whole session (observed 2026-09-23, session 114825).
"""
from bouzecode.backend.agent.providers import types as provider_types
from bouzecode.backend.agent.providers.backends import openrouter_stream


class _FakeResp:
    """Minimal stand-in for requests' streaming Response (encoding is assigned)."""
    encoding = None
    status_code = 200

    def iter_lines(self, *a, **kw):  # pragma: no cover - never reached (_iter_sse faked)
        return iter(())


_BATCH_TEXT = (
    'Reading the file.<tool_calls>'
    '<tool_use name="Read" id="a1"><param name="file_path">/tmp/x.py</param></tool_use>'
    '</tool_calls>'
)


def _run(chunks, **kwargs):
    """Drive stream_openrouter over a canned list of SSE chunks; return its events."""
    return list(openrouter_stream.stream_openrouter(
        api_key="k",
        model="claude-opus-5",
        system="sys",
        messages=[{"role": "user", "content": "hi"}],
        tool_schemas=[],
        config={},
        session_factory=lambda: None,
        send_reasoning=False,
        **kwargs,
    ))


def _install(monkeypatch, chunks):
    monkeypatch.setattr(openrouter_stream, "post_with_retry", lambda fn, **_kw: _FakeResp())
    monkeypatch.setattr(openrouter_stream, "_iter_sse", lambda resp, watchdog=None: iter(chunks))


def _assistant_turn(events):
    turns = [e for e in events if isinstance(e, provider_types.AssistantTurn)]
    assert len(turns) == 1, f"expected exactly one AssistantTurn, got {len(turns)}"
    return turns[0]


def test_usage_chunk_after_closed_batch_is_still_counted(monkeypatch):
    """The trailing usage-only chunk must reach the AssistantTurn."""
    _install(monkeypatch, [
        {"choices": [{"delta": {"content": _BATCH_TEXT}}]},
        {"choices": [], "usage": {"prompt_tokens": 1000, "completion_tokens": 50}},
    ])

    turn = _assistant_turn(_run([]))

    assert turn.in_tokens == 1000
    assert turn.out_tokens == 50
    assert turn.tool_calls and turn.tool_calls[0]["name"] == "Read"


def test_usage_after_batch_with_anthropic_field_names(monkeypatch):
    """Same drain, LiteLLM pass-through convention (input/output + cache fields)."""
    _install(monkeypatch, [
        {"choices": [{"delta": {"content": _BATCH_TEXT}}]},
        {"choices": [], "usage": {
            "input_tokens": 1200,
            "output_tokens": 80,
            "cache_read_input_tokens": 900,
            "cache_creation_input_tokens": 100,
        }},
    ])

    turn = _assistant_turn(_run([]))

    # 1200 total - 900 lus = 300 non lus en cache, dont les 100 écrits (convention de la
    # chaîne : l'entrée compte l'écriture de cache, cf. registry).
    assert turn.in_tokens == 300
    assert turn.out_tokens == 80
    assert turn.cache_read_tokens == 900
    assert turn.cache_creation_tokens == 100


def test_text_emitted_after_the_batch_is_ignored(monkeypatch):
    """Draining must not append post-batch text to the assistant message."""
    _install(monkeypatch, [
        {"choices": [{"delta": {"content": _BATCH_TEXT}}]},
        {"choices": [{"delta": {"content": "TRAILING GARBAGE"}}]},
        {"choices": [], "usage": {"prompt_tokens": 10, "completion_tokens": 2}},
    ])

    turn = _assistant_turn(_run([]))

    assert "TRAILING GARBAGE" not in turn.text
    assert turn.in_tokens == 10


def test_runaway_stream_after_batch_does_not_hang(monkeypatch):
    """No usage ever emitted: the drain is bounded, the generator still finishes."""
    endless = [{"choices": [{"delta": {"content": _BATCH_TEXT}}]}]
    endless += [{"choices": [{"delta": {"content": "x"}}]} for _ in range(5000)]
    _install(monkeypatch, endless)

    turn = _assistant_turn(_run([]))

    assert turn.in_tokens == 0  # nothing was reported by the endpoint
    assert turn.tool_calls and turn.tool_calls[0]["name"] == "Read"
