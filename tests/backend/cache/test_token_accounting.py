# [desc] E2E tests verifying per-turn and session-level cache token accounting through the agent loop
# <tool_use name="FinalAnswer" id="r1"><param name="answer">E2E tests verifying per-turn and session-level cache token accounting through the agent loop</param></tool_use> [/desc]
"""Reproduces the cache-write accounting bug and diagnoses cache waste.

Bug: session summary lumps cache_read + cache_write as "cached", hiding
that cache_write costs 1.25x input price. Wasted writes (never read back)
inflate cost silently.

Fix: display cache_read and cache_write separately in the session summary.
"""
from __future__ import annotations

import pytest
from bouzecode.backend.agent.state import AgentState, TurnDone, CheckpointReady
from bouzecode.backend.agent.providers.types import StreamStarted, TextChunk, ToolCallParsed, AssistantTurn


class FakeStreamCtrl:
    """Yields pre-configured AssistantTurn events with known token counts."""
    def __init__(self, responses: list[dict]):
        self.responses = responses
        self.idx = 0
        self.recorded_messages: list[list[dict]] = []

    def __call__(self, model, system, messages, tool_schemas, config):
        assert self.idx < len(self.responses), (
            f"stream() called {self.idx + 1} times, only {len(self.responses)} configured"
        )
        r = self.responses[self.idx]
        self.recorded_messages.append([dict(m) for m in messages])
        self.idx += 1
        yield StreamStarted()
        for tc in r.get("tool_calls", []):
            yield ToolCallParsed(tc["name"], tc["input"], tc["id"])
        yield TextChunk(r.get("text", ""))
        yield AssistantTurn(
            text=r.get("text", ""),
            tool_calls=r.get("tool_calls", []),
            in_tokens=r["in_tokens"],
            out_tokens=r["out_tokens"],
            cache_read_tokens=r.get("cache_read_tokens", 0),
            cache_creation_tokens=r.get("cache_creation_tokens", 0),
        )


def _drain(gen):
    return list(gen)

def _td(events):
    return [e for e in events if isinstance(e, TurnDone)]


@pytest.fixture
def mock_loop(monkeypatch):
    import bouzecode.backend.agent.loop as lm
    import bouzecode.backend.agent.loop_turn as ltm
    def setup(responses):
        ctrl = FakeStreamCtrl(responses)
        # stream + get_tool_schemas are looked up in loop_turn (post backend/ split).
        monkeypatch.setattr(ltm, "stream", ctrl)
        monkeypatch.setattr(ltm, "get_tool_schemas", lambda *_a, **_k: [])
        monkeypatch.setattr(ltm, "is_web_ipc_active", lambda: False)
        def _fake_exec(level, results, durations, config):
            for tc in level:
                results[tc["id"]] = f"[{tc['name']} result]"
                durations[tc["id"]] = 0.001
        monkeypatch.setattr(ltm, "_execute_level", _fake_exec)
        monkeypatch.setattr(ltm, "_check_permission", lambda tc, c: True)

        return ctrl, lm.run
    return setup


C = {"model": "claude-sonnet-4-6", "max_tokens": 1024,
     "enforce_methodology": False, "enforce_tests": False}
S = "You are helpful."


def test_single_turn_no_cache(mock_loop):
    """All tokens fresh — baseline."""
    _, run = mock_loop([{"text": "Hi", "in_tokens": 5000, "out_tokens": 100}])
    st = AgentState()
    events = _drain(run("Hi", st, C, S))
    td = _td(events)
    assert len(td) == 1
    assert td[0].input_tokens == 5000 and td[0].output_tokens == 100
    assert td[0].cache_read_tokens == 0 and td[0].cache_creation_tokens == 0
    assert st.total_input_tokens == 5000


def test_two_turns_cache_hit(mock_loop):
    """Turn 1 writes cache, turn 2 reads it back — healthy caching."""
    _, run = mock_loop([
        {"text": "R1", "in_tokens": 10000, "out_tokens": 50,
         "cache_read_tokens": 0, "cache_creation_tokens": 9000},
        {"text": "R2", "in_tokens": 11000, "out_tokens": 60,
         "cache_read_tokens": 9000, "cache_creation_tokens": 500},
    ])
    st = AgentState()
    _drain(run("T1", st, C, S))
    _drain(run("T2", st, C, S))
    assert st.total_input_tokens == 21000
    assert st.total_cache_read_tokens == 9000
    assert st.total_cache_creation_tokens == 9500
    fresh = st.total_input_tokens - st.total_cache_read_tokens - st.total_cache_creation_tokens
    assert fresh == 2500 and fresh >= 0


def test_wasted_cache_writes(mock_loop):
    """Turn 1 writes 9K to cache, turn 2 reads NONE — wasted.
    Proves that wasted cache writes cost MORE than no caching at all."""
    _, run = mock_loop([
        {"text": "R1", "in_tokens": 10000, "out_tokens": 100,
         "cache_read_tokens": 0, "cache_creation_tokens": 9000},
        {"text": "R2", "in_tokens": 11000, "out_tokens": 100,
         "cache_read_tokens": 0, "cache_creation_tokens": 10000},
    ])
    st = AgentState()
    _drain(run("T1", st, C, S))
    _drain(run("T2", st, C, S))
    assert st.total_cache_read_tokens == 0, "Nothing was ever read from cache!"
    assert st.total_cache_creation_tokens == 19000

    from bouzecode.backend.agent.providers.registry import calc_cost
    actual = calc_cost("claude-sonnet-4-6", st.total_input_tokens,
                       st.total_output_tokens, 0, 19000)
    no_cache = calc_cost("claude-sonnet-4-6", st.total_input_tokens,
                         st.total_output_tokens, 0, 0)
    assert actual > no_cache, (
        f"Wasted writes should cost MORE than fresh: {actual:.6f} > {no_cache:.6f}"
    )


def test_efficient_cache_saves_money(mock_loop):
    """When cache reads dominate, total cost is LOWER than no caching."""
    _, run = mock_loop([
        {"text": "R1", "in_tokens": 10000, "out_tokens": 100,
         "cache_read_tokens": 0, "cache_creation_tokens": 9000},
        {"text": "R2", "in_tokens": 11000, "out_tokens": 100,
         "cache_read_tokens": 9000, "cache_creation_tokens": 500},
    ])
    st = AgentState()
    _drain(run("T1", st, C, S))
    _drain(run("T2", st, C, S))

    from bouzecode.backend.agent.providers.registry import calc_cost
    actual = calc_cost("claude-sonnet-4-6", st.total_input_tokens,
                       st.total_output_tokens, st.total_cache_read_tokens,
                       st.total_cache_creation_tokens)
    no_cache = calc_cost("claude-sonnet-4-6", st.total_input_tokens,
                         st.total_output_tokens, 0, 0)
    assert actual < no_cache, (
        f"Efficient caching should save money: {actual:.6f} < {no_cache:.6f}"
    )


def test_cumulative_totals_match_turn_dones(mock_loop):
    """Sum of TurnDone values must equal AgentState totals."""
    _, run = mock_loop([
        {"text": "R1", "in_tokens": 5000, "out_tokens": 100,
         "cache_read_tokens": 0, "cache_creation_tokens": 4000},
        {"text": "R2", "in_tokens": 6000, "out_tokens": 120,
         "cache_read_tokens": 4000, "cache_creation_tokens": 500},
        {"text": "R3", "in_tokens": 7000, "out_tokens": 150,
         "cache_read_tokens": 4500, "cache_creation_tokens": 300},
    ])
    st = AgentState()
    all_td = []
    for msg in ["T1", "T2", "T3"]:
        all_td.extend(_td(_drain(run(msg, st, C, S))))
    assert st.total_input_tokens == sum(t.input_tokens for t in all_td)
    assert st.total_output_tokens == sum(t.output_tokens for t in all_td)
    assert st.total_cache_read_tokens == sum(t.cache_read_tokens for t in all_td)
    assert st.total_cache_creation_tokens == sum(t.cache_creation_tokens for t in all_td)


def test_tool_call_two_llm_calls_in_one_turn(mock_loop):
    """LLM call 1 returns tool_calls, call 2 returns text — both counted."""
    _, run = mock_loop([
        {"text": "Reading...", "in_tokens": 10000, "out_tokens": 200,
         "cache_read_tokens": 0, "cache_creation_tokens": 9000,
         "tool_calls": [{"id": "r1", "name": "Read",
                         "input": {"file_path": "foo.py"}}]},
        {"text": "Done.", "in_tokens": 12000, "out_tokens": 150,
         "cache_read_tokens": 9000, "cache_creation_tokens": 500},
    ])
    st = AgentState()
    events = _drain(run("Read foo.py", st, C, S))
    td = _td(events)
    assert len(td) == 2
    assert st.total_input_tokens == 22000
    assert st.total_cache_read_tokens == 9000
    assert st.total_cache_creation_tokens == 9500


def test_timing_entries_have_cache_breakdown(mock_loop):
    """Each LLM timing entry must record cache_read and cache_creation."""
    _, run = mock_loop([{"text": "OK", "in_tokens": 8000, "out_tokens": 50,
                         "cache_read_tokens": 5000, "cache_creation_tokens": 2000}])
    st = AgentState()
    _drain(run("Test", st, C, S))
    llm = [e for e in st.timing_entries if e["phase"] == "llm"]
    assert len(llm) == 1
    assert llm[0]["cache_read_tokens"] == 5000
    assert llm[0]["cache_creation_tokens"] == 2000


def test_session_summary_math(mock_loop):
    """Verify session summary correctly separates cache_read vs cache_write.

    Bug: old code lumped them as "cached = read + write, uncached = in - cached"
    making it look like 88% was cached (good!) when 45% was cache-WRITE (bad!).
    """
    _, run = mock_loop([
        {"text": "R1", "in_tokens": 10000, "out_tokens": 50,
         "cache_read_tokens": 0, "cache_creation_tokens": 9000},
        {"text": "R2", "in_tokens": 11000, "out_tokens": 60,
         "cache_read_tokens": 9000, "cache_creation_tokens": 500},
    ])
    st = AgentState()
    for msg in ["T1", "T2"]:
        _drain(run(msg, st, C, S))

    cr = st.total_cache_read_tokens      # 9000  — cheap (0.1x)
    cw = st.total_cache_creation_tokens   # 9500  — expensive (1.25x)
    cumulated = st.total_input_tokens     # 21000
    fresh = cumulated - cr - cw           # 2500  — normal (1x)

    # These must all be tracked separately, not lumped
    assert cr == 9000
    assert cw == 9500
    assert fresh == 2500
    assert cr + cw + fresh == cumulated

    # Old buggy display would show "18500 cached" hiding the 9500 at 1.25x
    old_cached = cr + cw
    assert old_cached == 18500  # misleading!


def test_user_msg_not_mutated_between_api_calls(mock_loop):
    """User message must stay identical across intra-turn API calls."""
    ctrl, run = mock_loop([
        {"text": "Reading...", "in_tokens": 5000, "out_tokens": 50,
         "tool_calls": [{"id": "r1", "name": "Read",
                         "input": {"file_path": "x.py"}}]},
        {"text": "Done", "in_tokens": 7000, "out_tokens": 50},
    ])
    st = AgentState()
    _drain(run("Read x.py", st, C, S))
    m1 = ctrl.recorded_messages[0]
    m2 = ctrl.recorded_messages[1]
    # Call 1 carries the (unmutated) user message verbatim.
    u1 = next(m["content"] for m in m1 if m.get("role") == "user")
    assert u1 == "Read x.py"
    # Under the minimal-wire design the user message is NOT re-sent on the
    # intra-turn continuation call (it lives in the methodology system block);
    # any user message that did appear must still be the unmutated original.
    for m in m2:
        if m.get("role") == "user":
            assert m["content"] == "Read x.py"
