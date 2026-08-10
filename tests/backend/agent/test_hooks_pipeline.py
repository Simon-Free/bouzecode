# [desc] Tests for the hook pipeline: named catalog, event registry, HookContext, and loop on_completion firing. [/desc]
"""Pipeline infra + loop firing. No unittest.mock — pure fakes + pytest.monkeypatch.

Covers: register_hook/fire/reset, the named-hook catalog (builtin), HookContext /
completion_context field derivation, and that loop.run fires on_completion on a
GRACEFUL close (FinalAnswer, text-with-no-tools) but NOT on assistant_none.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from bouzecode.backend.agent.hooks import pipeline
from bouzecode.backend.agent.hooks.context import HookContext, completion_context


@pytest.fixture(autouse=True)
def _clean_registry():
    pipeline.reset()
    yield
    pipeline.reset()


# ── event registry ────────────────────────────────────────────────────────────

def test_register_fire_reset():
    seen = []
    pipeline.register_hook("on_completion", lambda ctx: seen.append(ctx))
    ctx = HookContext(event="on_completion")
    pipeline.fire("on_completion", ctx)
    assert seen == [ctx]
    pipeline.reset()
    pipeline.fire("on_completion", ctx)
    assert seen == [ctx]  # unchanged: reset cleared the wiring


def test_fire_unknown_event_is_noop():
    pipeline.fire("does_not_exist", HookContext())  # must not raise


def test_failing_hook_does_not_abort_others(capsys):
    order = []

    def boom(ctx):
        raise RuntimeError("kaboom")

    pipeline.register_hook("on_completion", boom)
    pipeline.register_hook("on_completion", lambda ctx: order.append("ran"))
    pipeline.fire("on_completion", HookContext())
    assert order == ["ran"]  # second hook still ran
    assert "kaboom" in capsys.readouterr().err  # logged loudly, not silent


# ── named catalog (builtin) ───────────────────────────────────────────────────

def test_builtin_named_hook_present():
    hook = pipeline.get_named_hook("run_completion_chain")
    assert hook is not None
    assert hook.event == "on_completion"
    assert "run_completion_chain" in pipeline.all_named_hooks()


def test_register_named_wires_to_event():
    assert pipeline.register_named("run_completion_chain") is True
    assert "on_completion" in pipeline.registered_events()
    assert pipeline.register_named("no_such_hook") is False


def test_reset_named_reloads_builtin():
    pipeline.reset_named()
    assert pipeline.get_named_hook("run_completion_chain") is not None


# ── HookContext / completion_context ──────────────────────────────────────────

def test_completion_context_fields(monkeypatch):
    monkeypatch.setenv("BOUZECODE_WEB_IPC_DIR", r"C:\agents\abc123def456.ipc")
    monkeypatch.setenv("BOUZECODE_RUN_KIND", "validate")
    state = SimpleNamespace(messages=[
        {"role": "assistant", "content": "working"},
        {"role": "assistant", "content": "",
         "tool_calls": [{"name": "FinalAnswer", "input": {"answer": "RAPPORT: done"}}]},
    ])
    ctx = completion_context(state, {"_task_classification_result": "coder"}, "final_answer")
    assert ctx.event == "on_completion"
    assert ctx.self_id == "abc123def456"  # ipc dir stem
    assert ctx.run_kind == "validate"
    assert ctx.profile == "coder"
    assert ctx.final_text == "RAPPORT: done"
    assert ctx.close_reason == "final_answer"


def test_completion_context_ungoverned(monkeypatch):
    monkeypatch.delenv("BOUZECODE_WEB_IPC_DIR", raising=False)
    state = SimpleNamespace(messages=[{"role": "assistant", "content": "plain text answer"}])
    ctx = completion_context(state, {}, "text_no_tools")
    assert ctx.self_id == ""  # CLI / ungoverned
    assert ctx.run_kind == "work"
    assert ctx.final_text == "plain text answer"


# ── loop firing (graceful vs non-graceful) ────────────────────────────────────

def _run_loop_capturing(monkeypatch, fake_stream, *, tool_break=False, no_tools_break=False):
    from bouzecode.backend.agent import loop
    from bouzecode.backend.agent.loop_context import TurnAction
    from bouzecode.backend.agent.state import AgentState

    captured: list = []
    pipeline.register_hook("on_completion", lambda ctx: captured.append(ctx))
    monkeypatch.setenv("BOUZECODE_RUN_KIND", "work")
    monkeypatch.delenv("BOUZECODE_WEB_IPC_DIR", raising=False)
    monkeypatch.setattr(loop, "stream_llm_turn", fake_stream)
    if no_tools_break:
        monkeypatch.setattr(loop, "handle_no_tools", lambda s, c, ctx: TurnAction.BREAK)
    if tool_break:
        def fake_exec(tool_calls, state, config, ctx):
            ctx.action = TurnAction.BREAK
            return
            yield  # pragma: no cover — make it a generator
        monkeypatch.setattr(loop, "execute_tool_calls", fake_exec)
        monkeypatch.setattr(loop, "enforce_methodology",
                            lambda tcs, s, c, ctx: setattr(ctx, "_final_tool_calls", tcs))

    state = AgentState()
    config = {"recover_memory": False, "enforce_methodology": False}
    list(loop.run("hi", state, config, "sys"))
    return captured


def _fake_turn(text, tool_calls):
    return SimpleNamespace(text=text, tool_calls=tool_calls, in_tokens=0, out_tokens=0,
                           cache_read_tokens=0, cache_creation_tokens=0)


def test_loop_fires_on_text_no_tools(monkeypatch):
    from bouzecode.backend.agent.loop_context import TurnAction

    def fake_stream(state, config, sp, ctx, cc):
        ctx.assistant_turn = _fake_turn("all done", [])
        ctx.action = TurnAction.PROCEED
        return
        yield  # pragma: no cover

    captured = _run_loop_capturing(monkeypatch, fake_stream, no_tools_break=True)
    assert [c.close_reason for c in captured] == ["text_no_tools"]
    assert captured[0].final_text == "all done"


def test_loop_fires_on_final_answer(monkeypatch):
    from bouzecode.backend.agent.loop_context import TurnAction
    fa = [{"name": "FinalAnswer", "id": "fa1", "input": {"answer": "RAPPORT: shipped"}}]

    def fake_stream(state, config, sp, ctx, cc):
        ctx.assistant_turn = _fake_turn("", fa)
        ctx.action = TurnAction.PROCEED
        return
        yield  # pragma: no cover

    captured = _run_loop_capturing(monkeypatch, fake_stream, tool_break=True)
    assert [c.close_reason for c in captured] == ["final_answer"]
    assert captured[0].final_text == "RAPPORT: shipped"


def test_loop_does_not_fire_on_assistant_none(monkeypatch):
    from bouzecode.backend.agent.loop_context import TurnAction

    def fake_stream(state, config, sp, ctx, cc):
        ctx.assistant_turn = None
        ctx.action = TurnAction.PROCEED
        return
        yield  # pragma: no cover

    captured = _run_loop_capturing(monkeypatch, fake_stream)
    assert captured == []  # non-graceful close never fires on_completion


def test_loop_fires_on_final_answer_deferred(monkeypatch):
    """FIX #23: a deferred close (FinalAnswer + queued Bash checks) STILL fires
    on_completion, with close_reason 'final_answer_deferred' and the FinalAnswer as
    final_text; the DeferredChecks exception still propagates to the repl."""
    from bouzecode.backend.agent import loop
    from bouzecode.backend.agent.loop_context import TurnAction
    from bouzecode.backend.agent.state import AgentState
    from bouzecode.backend.tools.interaction import DeferredChecks
    from bouzecode.backend.agent.hooks import pipeline as _pl

    fa = [{"name": "FinalAnswer", "id": "fa1", "input": {"answer": "RAPPORT: deferred"}}]
    captured: list = []
    _pl.register_hook("on_completion", lambda ctx: captured.append(ctx))
    monkeypatch.setenv("BOUZECODE_RUN_KIND", "work")
    monkeypatch.delenv("BOUZECODE_WEB_IPC_DIR", raising=False)

    def fake_stream(state, config, sp, ctx, cc):
        ctx.assistant_turn = _fake_turn("", fa)
        ctx.action = TurnAction.PROCEED
        return
        yield  # pragma: no cover

    def fake_exec(tool_calls, state, config, ctx):
        raise DeferredChecks(answer="RAPPORT: deferred", checks=[{"command": "pytest"}])
        yield  # pragma: no cover — generator

    monkeypatch.setattr(loop, "stream_llm_turn", fake_stream)
    monkeypatch.setattr(loop, "execute_tool_calls", fake_exec)
    monkeypatch.setattr(loop, "enforce_methodology",
                        lambda tcs, s, c, ctx: setattr(ctx, "_final_tool_calls", tcs))

    state = AgentState()
    config = {"recover_memory": False, "enforce_methodology": False}
    with pytest.raises(DeferredChecks):
        list(loop.run("hi", state, config, "sys"))
    assert [c.close_reason for c in captured] == ["final_answer_deferred"]
    assert captured[0].final_text == "RAPPORT: deferred"


def test_loop_does_not_fire_on_partial_stream(monkeypatch):
    """A partial_stream close is non-graceful and must NOT fire on_completion."""
    from bouzecode.backend.agent import loop
    from bouzecode.backend.agent.loop_context import TurnAction

    fa = [{"name": "SomeTool", "id": "t1", "input": {}}]

    def fake_stream(state, config, sp, ctx, cc):
        ctx.assistant_turn = _fake_turn("", fa)
        ctx.action = TurnAction.PROCEED
        return
        yield  # pragma: no cover

    def fake_exec(tool_calls, state, config, ctx):
        ctx.action = TurnAction.PROCEED
        ctx.partial_stream = True
        return
        yield  # pragma: no cover

    monkeypatch.setattr(loop, "stream_llm_turn", fake_stream)
    monkeypatch.setattr(loop, "execute_tool_calls", fake_exec)
    monkeypatch.setattr(loop, "enforce_methodology",
                        lambda tcs, s, c, ctx: setattr(ctx, "_final_tool_calls", tcs))

    from bouzecode.backend.agent.state import AgentState
    captured: list = []
    pipeline.register_hook("on_completion", lambda ctx: captured.append(ctx))
    monkeypatch.delenv("BOUZECODE_WEB_IPC_DIR", raising=False)
    state = AgentState()
    config = {"recover_memory": False, "enforce_methodology": False}
    list(loop.run("hi", state, config, "sys"))
    assert captured == []  # partial_stream never fires on_completion
