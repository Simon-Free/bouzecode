"""Regression: turns.jsonl (the dump read by the /context viewer) MUST contain
the EXACT wire sent to the model, including the fresh-token reminders that
dispatch.stream() appends to a wire-only copy (_FRESH_REMINDER, audit note,
working memory).

Bug: stream_llm_turn dumps `messages_for_api` (the pre-dispatch, UNMUTATED
payload). dispatch.stream() mutates an INTERNAL copy (appends _FRESH_REMINDER
etc.) before hitting the API, but that copy is never dumped. So the viewer at
/api/sessions/<id>/turns/<n>/context shows a payload WITHOUT the reminder,
even though the model DID receive it. This breaks debugging of methodology
usage because the persisted payload != what the model actually saw.

Fix (STRAT-C): SystemPayload carries the mutated wire `messages`; stream_llm_turn
captures it (ctx.wire_messages) and dumps THAT in the enriched dump.
"""
import json
from pathlib import Path

import pytest

MARKER = "___WIRE_ONLY_REMINDER_MARKER___"


def _mk_state(session_id):
    class _CtxState:
        notes = {}

    class _State:
        turn_count = 7
        last_api_payload = None
        context_state = _CtxState()
        timing_entries = []

    return _State()


def test_turns_jsonl_contains_wire_only_reminder(tmp_path, monkeypatch):
    """The record persisted in turns.jsonl for the turn must contain the
    reminder that dispatch appended to the wire-only copy. RED before fix
    (dump uses the unmutated messages_for_api), GREEN after (dump uses the
    wire messages carried by SystemPayload)."""
    import bouzecode.backend.core.config as core_config
    import bouzecode.backend.agent.loop_turn as loop_turn
    from bouzecode.backend.agent.providers import (
        SystemPayload, AssistantTurn,
    )

    # turns.jsonl -> CONFIG_DIR/debug_payloads/<sid>/turns.jsonl (import tardif dans _payload_dir)
    monkeypatch.setattr(core_config, "CONFIG_DIR", tmp_path, raising=False)

    session_id = "wire-exactness-test"

    # build_messages_for_api produces the UNMUTATED upstream payload.
    upstream_messages = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "."},
        {"role": "tool", "content": "some tool result"},
    ]
    monkeypatch.setattr(
        loop_turn, "_build_messages_for_api",
        lambda state, config: [dict(m) for m in upstream_messages],
    )

    # Fake streamer = what dispatch.stream() really does: it appends the reminder
    # to a wire-only COPY, then yields SystemPayload carrying that mutated copy.
    def _fake_stream(model, system, messages, tool_schemas, config):
        wire = [dict(m) for m in messages]
        # emulate _append_to_last_user_message(wire, _BIGCTX_REMINDER)
        last = wire[-1]
        last["content"] = str(last.get("content", "")) + "\n" + MARKER
        yield SystemPayload(["sys block"], tools=None, messages=wire)
        yield AssistantTurn(
            text="done", tool_calls=[],
            in_tokens=10, out_tokens=5,
            cache_read_tokens=0, cache_creation_tokens=0,
        )

    monkeypatch.setattr(loop_turn, "stream", _fake_stream)

    # overflow budget is irrelevant here; import tardif dans stream_llm_turn
    # -> patch on the overflow_budget module.
    import bouzecode.backend.agent.overflow_budget as overflow_budget
    monkeypatch.setattr(
        overflow_budget, "dynamic_overflow_limit",
        lambda state, config: 100000, raising=False,
    )

    from bouzecode.backend.agent.loop_context import LoopContext
    ctx = LoopContext()
    config = {"model": "claude-sonnet-4", "_session_id": session_id}
    state = _mk_state(session_id)

    gen = loop_turn.stream_llm_turn(state, config, "system prompt", ctx,
                                    cancel_check=lambda: False)
    for _ in gen:
        pass

    dump_path = tmp_path / "debug_payloads" / session_id / "turns.jsonl"
    assert dump_path.exists(), "turns.jsonl was not written"
    records = [json.loads(l) for l in dump_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    # _load_turn_dumps keeps the LAST record for a given turn.
    last_record = [r for r in records if r["turn"] == state.turn_count][-1]
    blob = json.dumps(last_record["messages"], ensure_ascii=False)
    assert MARKER in blob, (
        "the persisted turns.jsonl payload does NOT contain the wire-only "
        "reminder the model actually received"
    )
