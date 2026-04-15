# [desc] Main agent loop: streams LLM responses, manages tool execution, permissions, compaction, and timing. [/desc]
from __future__ import annotations

import queue
import threading
import time
from typing import Generator

from tool_registry import get_tool_schemas
from providers import stream, AssistantTurn, TextChunk, ThinkingChunk, StreamStarted
from compaction import maybe_compact
from followup_compaction import build_messages_for_api as _build_messages_for_api
from context_gc import GCState

from .state import AgentState, ToolStart, ToolEnd, TurnDone, PermissionRequest, CheckpointReady
from .dag import _build_dag_levels, _compute_downstream, _execute_level
from .permissions import _check_permission, _permission_desc, _propagate_denials
from tools.interaction import PausedForInput, is_web_ipc_active


_SENTINEL = object()


class _CancelledTurn(Exception):
    """Raised mid-stream when cancel_check() becomes true."""


def _interruptible_iter(gen, cancel_check=None):
    q: queue.Queue = queue.Queue()

    def _worker():
        try:
            for item in gen:
                q.put(item)
        except BaseException as exc:
            q.put(exc)
        finally:
            q.put(_SENTINEL)

    t = threading.Thread(target=_worker, daemon=True)
    t.start()

    while True:
        try:
            item = q.get(timeout=0.2)
        except queue.Empty:
            if cancel_check and cancel_check():
                raise _CancelledTurn()
            continue
        if item is _SENTINEL:
            break
        if isinstance(item, BaseException):
            raise item
        yield item


def run(
    user_message: str | None,
    state: AgentState,
    config: dict,
    system_prompt: str,
    depth: int = 0,
    cancel_check=None,
) -> Generator:
    if user_message is not None:
        user_msg = {"role": "user", "content": user_message}
        pending_img = config.pop("_pending_image", None)
        if pending_img:
            user_msg["images"] = [pending_img]
        state.messages.append(user_msg)
        yield CheckpointReady(len(state.messages))

    config = {**config, "_depth": depth, "_system_prompt": system_prompt}

    if not hasattr(state, 'gc_state'):
        state.gc_state = GCState()
    config["_gc_state"] = state.gc_state

    if depth == 0 and state.conversation_start == 0.0:
        state.conversation_start = time.monotonic()

    while True:
        if cancel_check and cancel_check():
            return
        state.turn_count += 1
        assistant_turn: AssistantTurn | None = None

        last_in = next(
            (e.get("in_tokens", 0) for e in reversed(state.timing_entries)
             if e["phase"] == "llm"), 0
        )
        if maybe_compact(state, config):
            state.distinct_base += last_in

        messages_for_api = _build_messages_for_api(state, config)

        llm_start = time.monotonic()
        first_event_at: float | None = None
        first_text_at: float | None = None
        last_thinking_at: float | None = None
        try:
            stream_iter = _interruptible_iter(stream(
                model=config["model"],
                system=system_prompt,
                messages=messages_for_api,
                tool_schemas=get_tool_schemas(),
                config=config,
            ), cancel_check=cancel_check)
            for event in stream_iter:
                if isinstance(event, StreamStarted):
                    if first_event_at is None:
                        first_event_at = time.monotonic()
                elif isinstance(event, (TextChunk, ThinkingChunk)):
                    now = time.monotonic()
                    if first_event_at is None:
                        first_event_at = now
                    if isinstance(event, ThinkingChunk):
                        last_thinking_at = now
                    elif isinstance(event, TextChunk) and first_text_at is None:
                        first_text_at = now
                    yield event
                elif isinstance(event, AssistantTurn):
                    assistant_turn = event
        except _CancelledTurn:
            return
        llm_end = time.monotonic()

        ttft = (first_event_at - llm_start) if first_event_at else 0.0
        if first_text_at is not None:
            thinking_dur = max(0.0, first_text_at - (first_event_at or first_text_at))
            streaming_dur = llm_end - first_text_at
        elif last_thinking_at is not None:
            thinking_dur = last_thinking_at - (first_event_at or last_thinking_at)
            streaming_dur = 0.0
        else:
            thinking_dur, streaming_dur = 0.0, llm_end - (first_event_at or llm_start)
        at = assistant_turn
        out_tok = at.out_tokens if at else 0
        cache_read = at.cache_read_tokens if at else 0
        cache_create = at.cache_creation_tokens if at else 0
        state.timing_entries.append({
            "phase": "llm", "duration": llm_end - llm_start,
            "ttft": ttft, "thinking": thinking_dur, "streaming": streaming_dur,
            "out_tokens": out_tok, "in_tokens": at.in_tokens if at else 0,
            "cache_read_tokens": cache_read, "cache_creation_tokens": cache_create,
            "tokens_per_sec": (out_tok / streaming_dur) if streaming_dur > 0 else 0.0,
        })

        if assistant_turn is None:
            break

        from compaction import estimate_tokens
        state.compaction_log.append({
            "event": "llm_call", "timestamp": time.time(), "turn": state.turn_count,
            "api_input_tokens": at.in_tokens, "api_output_tokens": at.out_tokens,
            "api_cache_read": at.cache_read_tokens, "api_cache_create": at.cache_creation_tokens,
            "est_message_tokens": estimate_tokens(state.messages),
            "message_count": len(state.messages), "has_tool_calls": bool(at.tool_calls),
        })

        state.messages.append({
            "role": "assistant", "content": at.text, "tool_calls": at.tool_calls,
        })
        state.total_input_tokens += at.in_tokens
        state.total_output_tokens += at.out_tokens
        state.total_cache_read_tokens += at.cache_read_tokens
        state.total_cache_creation_tokens += at.cache_creation_tokens
        yield TurnDone(at.in_tokens, at.out_tokens, at.cache_read_tokens,
                       at.cache_creation_tokens)

        if not at.tool_calls:
            yield CheckpointReady(len(state.messages))
            break

        # Deduplicate tool calls by ID (model may echo duplicates)
        _seen_ids: set[str] = set()
        tool_calls = [tc for tc in at.tool_calls
                      if tc["id"] not in _seen_ids and not _seen_ids.add(tc["id"])]
        state.messages[-1]["tool_calls"] = tool_calls

        permitted_map: dict[str, bool] = {}
        denied_results: dict[str, str] = {}
        for tc in tool_calls:
            yield ToolStart(tc["name"], tc["input"])
            permitted = _check_permission(tc, config)
            if not permitted:
                if config.get("permission_mode") == "plan":
                    permitted = False
                else:
                    req = PermissionRequest(description=_permission_desc(tc))
                    yield req
                    permitted = req.granted
            permitted_map[tc["id"]] = permitted
            if not permitted:
                if config.get("permission_mode") == "plan":
                    plan_file = config.get("_plan_file", "")
                    denied_results[tc["id"]] = (
                        f"[Plan mode] Write operations are blocked except to the plan file: {plan_file}\n"
                        "Finish your analysis and write the plan to the plan file. "
                        "The user will run /plan done to exit plan mode and begin implementation."
                    )
                else:
                    denied_results[tc["id"]] = "Denied: user rejected this operation"

        _propagate_denials(tool_calls, permitted_map, denied_results)

        permitted_tcs = [tc for tc in tool_calls if permitted_map[tc["id"]]]
        results: dict[str, str] = dict(denied_results)
        durations: dict[str, float] = {tc["id"]: 0.0 for tc in tool_calls}

        levels, deps = _build_dag_levels(permitted_tcs)

        ask_tc = None
        if is_web_ipc_active():
            ask_tc = next(
                (tc for tc in permitted_tcs if tc["name"] == "AskUserQuestion"),
                None,
            )

        if ask_tc is None:
            for level in levels:
                _execute_level(level, results, durations, config)
        else:
            downstream = _compute_downstream(deps, {ask_tc["id"]})
            for level in levels:
                runnable = [tc for tc in level if tc["id"] not in downstream]
                if runnable:
                    _execute_level(runnable, results, durations, config)

        resolved_ids = set(results.keys())

        for tc in tool_calls:
            if tc["id"] in resolved_ids and permitted_map[tc["id"]]:
                state.timing_entries.append({"phase": tc["name"], "duration": durations[tc["id"]]})

        for tc in tool_calls:
            if tc["id"] not in resolved_ids:
                continue
            result = results[tc["id"]]
            yield ToolEnd(tc["name"], result, permitted_map[tc["id"]],
                          durations[tc["id"]])
            state.messages.append({
                "role": "tool", "tool_call_id": tc["id"],
                "name": tc["name"], "content": result,
            })

        if ask_tc is not None:
            pending_tcs = [tc for tc in tool_calls if tc["id"] not in resolved_ids]
            raise PausedForInput(
                question=ask_tc["input"]["question"],
                options=ask_tc["input"].get("options"),
                allow_freetext=ask_tc["input"].get("allow_freetext", True),
                ask_tc_id=ask_tc["id"],
                completed_results=dict(results),
                pending_tcs=pending_tcs,
            )

        yield CheckpointReady(len(state.messages))


def resume_paused(
    pending: dict,
    answer: str,
    state: AgentState,
    config: dict,
    system_prompt: str,
    cancel_check=None,
) -> Generator:
    """Resume a turn paused on AskUserQuestion: inject answer, run remaining tcs, continue."""
    ask_tc_id = pending["ask_tc_id"]
    pending_tcs = pending.get("pending_tcs", [])

    yield ToolEnd("AskUserQuestion", answer, True, 0.0)
    state.messages.append({
        "role": "tool", "tool_call_id": ask_tc_id,
        "name": "AskUserQuestion", "content": answer,
    })

    non_ask = [tc for tc in pending_tcs if tc["id"] != ask_tc_id]
    if non_ask:
        for tc in non_ask:
            yield ToolStart(tc["name"], tc["input"])

        results: dict[str, str] = {}
        durations: dict[str, float] = {tc["id"]: 0.0 for tc in non_ask}
        levels, _deps = _build_dag_levels(non_ask)
        for level in levels:
            _execute_level(level, results, durations, config)

        for tc in non_ask:
            result = results[tc["id"]]
            state.timing_entries.append({"phase": tc["name"], "duration": durations[tc["id"]]})
            yield ToolEnd(tc["name"], result, True, durations[tc["id"]])
            state.messages.append({
                "role": "tool", "tool_call_id": tc["id"],
                "name": tc["name"], "content": result,
            })

    yield CheckpointReady(len(state.messages))
    yield from run(None, state, config, system_prompt, cancel_check=cancel_check)
