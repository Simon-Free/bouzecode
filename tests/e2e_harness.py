# [desc] E2E testing harness: runs multi-turn bouzecode conversations with MockLLM and interactive prompt support. [/desc]
"""E2E testing harness for bouzecode.

Usage:
    from tests.e2e_harness import bouzecode

    result = bouzecode(messages=["Say exactly: PONG"])
    assert "PONG" in result.last_reply
"""
from __future__ import annotations

import re
import sys
import tempfile
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bouzecode.backend.agent.loop import run, resume_paused
from bouzecode.backend.agent.state import AgentState
from bouzecode.backend.core.config import load_config
from bouzecode.backend.tools.interaction import PausedForInput


@dataclass
class TurnResult:
    events: list = field(default_factory=list)
    reply: str | None = None


@dataclass
class ConversationResult:
    messages: list = field(default_factory=list)
    events: list = field(default_factory=list)
    turns: list[TurnResult] = field(default_factory=list)
    state: AgentState = field(default_factory=AgentState)
    # When mock_api is used, the real request bodies the client sent to the
    # (fake) Anthropic API — assert on the actual wire payload (system, messages,
    # cache_control) the full pipeline produced.
    recorded_requests: list = field(default_factory=list)

    @property
    def last_reply(self) -> str:
        """Last user-VISIBLE assistant text. XML-protocol turns store raw tool
        markup in content (it IS the wire format), so a closing meta-only
        compliance turn would otherwise shadow the real answer: strip tool/think
        markup like the display layer does and skip turns left empty by it.
        A FinalAnswer close IS the reply — the model puts the deliverable in the
        tool param, often leaving only narration as visible text."""
        if getattr(self.state, "final_answer", ""):
            return self.state.final_answer
        for msg in reversed(self.messages):
            if msg.get("role") != "assistant":
                continue
            content = msg.get("content", "")
            if isinstance(content, list):
                content = "\n".join(b["text"] for b in content if b.get("type") == "text")
            visible = _strip_assistant_markup(content)
            if visible:
                return visible
        return ""


_MARKUP_RE = re.compile(
    r"<thinking>.*?</thinking>|<tool_use\b.*?</tool_use>|<tool_use\b[^>]*/>",
    re.DOTALL,
)


def _strip_assistant_markup(content: str) -> str:
    """Remove <thinking> and <tool_use> blocks; return the remaining text."""
    return _MARKUP_RE.sub("", content).strip()


def _get_answer(
    question: str,
    options: list[dict] | None,
    replies: deque[str],
    on_question: Callable[[str, list], str] | None,
) -> str:
    if replies:
        return replies.popleft()
    if on_question:
        return on_question(question, options or [])
    raise RuntimeError(
        f"PausedForInput with no reply available. Question: {question!r}"
    )


def _drain_generator(gen, turn: TurnResult, all_events: list):
    for event in gen:
        turn.events.append(event)
        all_events.append(event)


def bouzecode(
    messages: list[str],
    *,
    mock_llm=None,
    mock_api: list | None = None,
    mock_tools: bool | dict | None = None,
    replies: list[str] | None = None,
    on_question: Callable[[str, list], str] | None = None,
    config_overrides: dict | None = None,
    system_prompt: str = "You are a helpful assistant. Be concise.",
    timeout_per_turn: float = 60.0,
) -> ConversationResult:
    """Run a full multi-turn conversation with the real LLM (or a mock).

    Args:
        messages: List of user messages to send sequentially.
        mock_llm: A MockLLM instance (from tests.fake_llm) — if provided,
            patches the LLM stream so no real API call is made.
        mock_tools: Controls tool execution when mock_llm is set:
            - None: real tool execution (default)
            - True: all tools return "[{name} executed]"
            - dict: mapping {tool_name: str_result} or {tool_name: callable}
        replies: Pre-queued answers for AskUserQuestion/plan validation (FIFO).
        on_question: Callback fallback for interactive prompts.
            Signature: (question: str, options: list[dict]) -> str
        config_overrides: Override config keys (e.g. model, max_tokens).
        system_prompt: System prompt for the conversation.
        timeout_per_turn: Max seconds per turn (unused currently, for future use).

    Returns:
        ConversationResult with full conversation history and events.
    """
    reply_queue = deque(replies or [])

    config = load_config()
    config["permission_mode"] = "accept-all"
    config["verbose"] = False
    config["task_classification"] = False  # no classification LLM call in tests
    config["close_validation"] = False     # no FinalAnswer-validator LLM call in tests

    tmpdir = Path(tempfile.mkdtemp(prefix="bouzecode_e2e_"))
    config["_cwd"] = str(tmpdir)

    if config_overrides:
        config.update(config_overrides)

    # --- Mock patching ---
    _patches = []
    _cleanups = []  # callables run in finally (env restore, etc.)
    _app = None     # mock-API Flask app, carries recorded request bodies
    if mock_llm is not None:
        import bouzecode.backend.agent.loop_turn as _lt
        _orig_stream = _lt.stream
        _orig_get_tool_schemas = _lt.get_tool_schemas
        _orig_is_web_ipc = _lt.is_web_ipc_active

        _lt.stream = mock_llm.stream
        _lt.get_tool_schemas = lambda *_a, **_k: []
        _lt.is_web_ipc_active = lambda: False
        _patches.append(("stream", _lt, _orig_stream))
        _patches.append(("get_tool_schemas", _lt, _orig_get_tool_schemas))
        _patches.append(("is_web_ipc_active", _lt, _orig_is_web_ipc))

        if mock_tools is not None:
            _orig_exec = _lt._execute_level

            def _fake_exec(level, results, durations, config):
                for tc in level:
                    if mock_tools is True:
                        results[tc["id"]] = f"[{tc['name']} executed]"
                    elif isinstance(mock_tools, dict):
                        val = mock_tools.get(tc["name"], f"[{tc['name']} executed]")
                        results[tc["id"]] = val(tc) if callable(val) else val
                    durations[tc["id"]] = 0.001

            _lt._execute_level = _fake_exec
            _patches.append(("_execute_level", _lt, _orig_exec))

        _orig_check = _lt._check_permission
        _lt._check_permission = lambda tc, c: True
        _patches.append(("_check_permission", _lt, _orig_check))

    if mock_api is not None:
        # API-level mock: the REAL pipeline runs (dispatch, get_tool_schemas,
        # wire serialization, anthropic_stream, SSE parsing, retry) against a fake
        # HTTP server. Do NOT patch stream/get_tool_schemas — only point the client
        # at the server and let the loop run hermetically otherwise.
        import os as _os
        from tests.mock_anthropic_server import start_mock_anthropic
        from tests import cache_conversation_helpers as _cch
        import bouzecode.backend.agent.loop_turn as _lt

        _url, _app = start_mock_anthropic(mock_api)
        _prev = {
            "base": _os.environ.get("ANTHROPIC_BASE_URL"),
            "key": _os.environ.get("ANTHROPIC_API_KEY"),
            "live": _cch.LIVE_API_ALLOWED,
        }
        _os.environ["ANTHROPIC_BASE_URL"] = _url
        _os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
        config["anthropic_api_key"] = _os.environ["ANTHROPIC_API_KEY"]
        _cch.LIVE_API_ALLOWED = True  # localhost mock, not the live socle

        _orig_web = _lt.is_web_ipc_active
        _lt.is_web_ipc_active = lambda: False
        _patches.append(("is_web_ipc_active", _lt, _orig_web))
        _orig_check = _lt._check_permission
        _lt._check_permission = lambda tc, c: True
        _patches.append(("_check_permission", _lt, _orig_check))

        def _restore_api_env(_p=_prev):
            for k, name in (("base", "ANTHROPIC_BASE_URL"), ("key", "ANTHROPIC_API_KEY")):
                if _p[k] is None:
                    _os.environ.pop(name, None)
                else:
                    _os.environ[name] = _p[k]
            _cch.LIVE_API_ALLOWED = _p["live"]
        _cleanups.append(_restore_api_env)

    state = AgentState()
    all_events: list = []
    turns: list[TurnResult] = []

    try:
        for user_msg in messages:
            turn = TurnResult()
            gen = run(user_msg, state, config, system_prompt)

            try:
                _drain_generator(gen, turn, all_events)
            except PausedForInput as e:
                answer = _get_answer(e.question, e.options, reply_queue, on_question)
                pending = {
                    "ask_tc_id": e.ask_tc_id,
                    "question": e.question,
                    "completed_results": e.completed_results,
                    "pending_tcs": e.pending_tcs,
                    "is_plan_validation": e.is_plan_validation,
                }
                resume_gen = resume_paused(pending, answer, state, config, system_prompt)
                try:
                    _drain_generator(resume_gen, turn, all_events)
                except PausedForInput as e2:
                    answer2 = _get_answer(e2.question, e2.options, reply_queue, on_question)
                    pending2 = {
                        "ask_tc_id": e2.ask_tc_id,
                        "question": e2.question,
                        "completed_results": e2.completed_results,
                        "pending_tcs": e2.pending_tcs,
                        "is_plan_validation": e2.is_plan_validation,
                    }
                    resume_gen2 = resume_paused(pending2, answer2, state, config, system_prompt)
                    _drain_generator(resume_gen2, turn, all_events)

            # Extract reply text from this turn
            for msg in reversed(state.messages):
                if msg.get("role") == "assistant":
                    content = msg.get("content", "")
                    if isinstance(content, str):
                        turn.reply = content
                    elif isinstance(content, list):
                        texts = [b["text"] for b in content if b.get("type") == "text"]
                        turn.reply = "\n".join(texts)
                    break

            turns.append(turn)

    finally:
        for attr_name, module, orig_val in _patches:
            setattr(module, attr_name, orig_val)
        for _c in _cleanups:
            _c()

    return ConversationResult(
        messages=list(state.messages),
        events=all_events,
        turns=turns,
        state=state,
        recorded_requests=list(_app.recorded_calls) if _app is not None else [],
    )
