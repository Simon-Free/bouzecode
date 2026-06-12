# [desc] Tests enforcement recovery: forced Methodology/Snippet side-calls augment tool batches before execution.
# <tool_use name="FinalAnswer" id="f1"><param name="answer">Tests enforcement recovery: forced Methodology/Snippet side-calls augment tool batches before execution.</param></tool_use> [/desc]
"""Enforcement contract: no in-wire bounce. enforce_methodology just dedups + proceeds.
Missing working memory is recovered by FORCED side-calls that augment the turn's batch
BEFORE it executes: Methodology (from this turn's thinking) is prepended if absent;
Snippets for still-uncovered Read/Skill results (already executed → content available)
are appended. The side LLM calls are mocked here — no network.
"""
import types

import pytest

from bouzecode.backend.agent import enforcement_call
from bouzecode.backend.agent.enforcement_call import (
    recover_methodology, recover_snippets, snippetable_results,
)
from bouzecode.backend.agent.loop_turn import enforce_methodology
from bouzecode.backend.agent.loop_context import LoopContext, TurnAction
from bouzecode.backend.context_manager.state import METHODOLOGY_NOTE
from bouzecode.backend.core.tool_registry import (
    ToolDef, register_tool, push_local_overlay, pop_local_overlay,
)


def _ctx(thinking="some reasoning"):
    ctx = LoopContext()
    ctx.thinking_parts = [thinking] if thinking else []
    return ctx


def _state(messages):
    return types.SimpleNamespace(messages=messages, total_tool_calls=0)


@pytest.fixture
def tools():
    push_local_overlay()
    register_tool(ToolDef(
        name="Read", func=lambda p, c: "x=1", snippetable=True, snippet_key="file",
        schema={"name": "Read", "input_schema": {"type": "object",
                "properties": {"file_path": {"type": "string"}}}}))
    register_tool(ToolDef(
        name="Methodology", func=lambda p, c: "meth ok",
        schema={"name": "Methodology", "input_schema": {"type": "object",
                "properties": {"content": {"type": "string"}}}}))
    register_tool(ToolDef(
        name="Snippet", func=lambda p, c: "snip ok",
        schema={"name": "Snippet", "input_schema": {"type": "object", "properties": {
                "file_path": {"type": "string"}, "tool_id": {"type": "string"},
                "ranges": {"type": "array"}, "discard": {"type": "boolean"},
                "label": {"type": "string"}}}}))
    register_tool(ToolDef(
        name="Glob", func=lambda p, c: "f.py",
        schema={"name": "Glob", "input_schema": {"type": "object",
                "properties": {"pattern": {"type": "string"}}}}))
    yield
    pop_local_overlay()


# ── enforce_methodology is now plain ─────────────────────────────────────────

def test_enforce_methodology_is_plain_and_dedups():
    state = _state([
        {"role": "user", "content": "go"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "r1", "name": "Read", "input": {"file_path": "a"}},
            {"id": "r1", "name": "Read", "input": {"file_path": "a"}}]},
    ])
    ctx = _ctx()
    result = enforce_methodology(state.messages[-1]["tool_calls"], state, {}, ctx)
    assert result is None                       # plain function, not a generator
    assert ctx.action == TurnAction.PROCEED
    assert len(ctx._final_tool_calls) == 1      # deduped by id
    assert not any(m["role"] == "user" and "ENFORCEMENT" in m.get("content", "")
                   for m in state.messages)     # no in-wire bounce message


# ── snippetable_results locates the read-bearing turn's results ──────────────

_BIG_CONTENT = "\n".join(f"line {i}" for i in range(60))


def test_snippetable_results_returns_reads_with_content():
    msgs = [
        {"role": "user", "content": "go"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "r1", "name": "Read", "input": {"file_path": "a.py"}}]},
        {"role": "tool", "tool_call_id": "r1", "name": "Read", "content": _BIG_CONTENT},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "g1", "name": "Glob", "input": {"pattern": "*"}}]},   # later non-read turn
    ]
    out = snippetable_results(msgs)
    assert out == [{"tool_id": "r1", "name": "Read", "file_path": "a.py",
                    "content": _BIG_CONTENT}]


def test_snippetable_results_ignores_small_reads():
    """Read result below SNIPPET_MIN_LINES is excluded from recovery."""
    msgs = [
        {"role": "user", "content": "go"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "r1", "name": "Read", "input": {"file_path": "small.py"}}]},
        {"role": "tool", "tool_call_id": "r1", "name": "Read", "content": "def foo(): pass"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "g1", "name": "Glob", "input": {"pattern": "*"}}]},
    ]
    assert snippetable_results(msgs) == []


# ── the two forced side-calls seed their context + force tool_choice ─────────

def test_recover_methodology_seeds_prev_and_thinking(monkeypatch):
    captured = {}

    def fake(tool_name, system, msg, config, **k):
        captured.update(tool_name=tool_name, msg=msg)
        return [{"id": "m1", "name": "Methodology", "input": {"content": "distilled"}}]

    monkeypatch.setattr(enforcement_call, "_ask_forced", fake)
    ctx = _ctx("exploré src/, il faut lire config.py")
    config = {"model": "deepseek-v4-pro",
              "_context_state": types.SimpleNamespace(notes={METHODOLOGY_NOTE: "## todo\n- [ ] démarrer"})}
    tc = recover_methodology(_state([]), config, ctx)
    assert tc["name"] == "Methodology" and captured["tool_name"] == "Methodology"
    assert "exploré src/" in captured["msg"]        # this turn's thinking is seeded
    assert "- [ ] démarrer" in captured["msg"]       # previous Methodology is seeded


def test_recover_methodology_none_without_thinking(monkeypatch):
    monkeypatch.setattr(enforcement_call, "_ask_forced",
                        lambda *a, **k: [{"id": "m1", "name": "Methodology", "input": {}}])
    assert recover_methodology(_state([]), {"model": "m"}, _ctx(thinking="")) is None


def test_recover_snippets_seeds_reads_and_thinking(monkeypatch):
    captured = {}

    def fake(tool_name, system, msg, config, **k):
        captured.update(tool_name=tool_name, msg=msg, required=k.get("required"))
        return [{"id": "s1", "name": "Snippet", "input": {"discard": True, "tool_id": "r1"}}]

    monkeypatch.setattr(enforcement_call, "_ask_forced", fake)
    snip_results = [{"tool_id": "r1", "name": "Read", "file_path": "a.py", "content": "def foo(): pass"}]
    out = recover_snippets(snip_results, _ctx("je dois figer a.py"), {"model": "m"})
    assert out and out[0]["name"] == "Snippet"
    assert captured["tool_name"] == "Snippet" and captured["required"] is True
    assert "def foo()" in captured["msg"]            # the read content is replayed
    assert "je dois figer a.py" in captured["msg"]   # this turn's thinking is seeded


def test_recover_snippets_noop_when_no_results():
    assert recover_snippets([], _ctx(), {"model": "m"}) == []


def test_ask_forced_pins_or_requires_tool_choice(tools, monkeypatch):
    from bouzecode.backend.agent import loop_turn as _lt
    from bouzecode.backend.agent.providers import AssistantTurn
    seen = {}

    def fake_stream(model, system, messages, tool_schemas, config):
        seen["tool_choice"] = config.get("_tool_choice")
        seen["depth"] = config.get("_depth")
        seen["tools"] = [s["name"] for s in tool_schemas]
        yield AssistantTurn("", [{"id": "m1", "name": "Methodology", "input": {"content": "x"}}],
                            0, 0, 0, 0)

    monkeypatch.setattr(_lt, "stream", fake_stream)
    out = enforcement_call._ask_forced("Methodology", "sys", "ctx", {"model": "m"})
    assert out and out[0]["name"] == "Methodology"
    assert seen["tool_choice"] == {"type": "function", "function": {"name": "Methodology"}}
    assert seen["depth"] == 1 and seen["tools"] == ["Methodology"]   # minimal payload

    enforcement_call._ask_forced("Snippet", "sys", "ctx", {"model": "m"}, required=True)
    assert seen["tool_choice"] == "required"          # Snippet may be multiple → required


# ── loop integration: the batch is augmented before execution ────────────────

def test_loop_prepends_methodology_when_missing(monkeypatch):
    """A turn emitting tools but no Methodology gets it prepended before execution."""
    from tests.e2e_harness import bouzecode
    from tests.fake_llm import MockLLM

    monkeypatch.setattr(enforcement_call, "recover_methodology",
                        lambda state, config, ctx: {"id": "rm", "name": "Methodology",
                                                    "input": {"content": "recovered"}})
    glob = '<tool_use name="Glob" id="g1"><param name="pattern">**/*.py</param></tool_use>'
    meth = '<tool_use name="Methodology" id="m9"><param name="content">done</param></tool_use>'
    mock = MockLLM([glob, f"Fini.\n{meth}"])
    result = bouzecode(["go"], mock_llm=mock, config_overrides={"recover_memory": True})

    asst = [m for m in result.messages if m.get("role") == "assistant" and m.get("tool_calls")]
    names = [tc["name"] for tc in asst[0]["tool_calls"]]
    assert names[0] == "Methodology"                 # prepended
    assert "Glob" in names                           # original work preserved


def test_loop_appends_snippet_for_uncovered_read(monkeypatch):
    """When the previous turn read a file and the current batch doesn't snippet it, a
    Snippet is recovered and appended to the current batch before execution."""
    from tests.e2e_harness import bouzecode
    from tests.fake_llm import MockLLM

    appended = {"called": 0}

    def fake_snips(snip_results, ctx, config, state=None):
        appended["called"] += 1
        appended["saw_read"] = any(r["name"] == "Read" for r in snip_results)
        return [{"id": "s9", "name": "Snippet", "input": {"tool_id": "r1", "discard": True}}]

    monkeypatch.setattr(enforcement_call, "recover_snippets", fake_snips)
    meth = '<tool_use name="Methodology" id="m1"><param name="content">m</param></tool_use>'
    read = '<tool_use name="Read" id="r1"><param name="file_path">/tmp/code.py</param></tool_use>'
    mock = MockLLM([f"{meth}\n{read}", f"Fini.\n{meth}"])   # turn1 reads; turn2 forgets Snippet
    result = bouzecode(["go"], mock_llm=mock,
                       mock_tools={"Read": _BIG_CONTENT},
                       config_overrides={"recover_memory": True})

    assert appended["called"] == 1 and appended["saw_read"]   # fired once, saw the read
    snippet_calls = [tc for m in result.messages if m.get("role") == "assistant"
                     for tc in (m.get("tool_calls") or []) if tc["name"] == "Snippet"]
    assert snippet_calls                                      # appended + executed
