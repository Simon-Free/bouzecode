# [desc] Main agent loop: orchestrates LLM streaming, tool execution, permissions, and turn management. [/desc]
from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
from typing import Generator

from .providers import ToolIdRemap
from .minimal_payload import build_messages_for_api as _build_messages_for_api

from .state import AgentState, ToolStart, ToolEnd, TurnDone, PermissionRequest, CheckpointReady
from .dag import _build_dag_levels, _compute_downstream, _execute_level
from .permissions import _check_permission, _permission_desc, _propagate_denials
from .id_uniquify import uniquify_tool_call_ids
from .payload_dump import dump_turn_payload
from ..tools.interaction import PausedForInput, is_web_ipc_active
from ..tools.plan_mode import PlanRejected

from .loop_context import LoopContext, TurnAction
from .loop_turn import stream_llm_turn, handle_no_tools, enforce_methodology, execute_tool_calls
from .task_classifier import classify


def _build_assistant_content(at_text: str, thinking_parts: list[str]) -> str:
    """Build assistant message content, prepending thinking tags if present."""
    if not thinking_parts:
        return at_text
    thinking_text = "".join(thinking_parts)
    if at_text and at_text.strip() != ".":
        return f"<thinking>\n{thinking_text}\n</thinking>\n\n{at_text}"
    return f"<thinking>\n{thinking_text}\n</thinking>"


class _CancelledTurn(Exception):
    """Raised mid-stream when cancel_check() becomes true."""


def _complete_pending_tool_calls(pending_tcs, state, config):
    """Execute tool_calls that didn't complete in a prior crashed run."""
    permitted_map: dict[str, bool] = {}
    denied_results: dict[str, str] = {}
    for tc in pending_tcs:
        yield ToolStart(tc["name"], tc["input"], tool_id=tc["id"])
        permitted = _check_permission(tc, config)
        if not permitted:
            req = PermissionRequest(description=_permission_desc(tc))
            yield req
            permitted = req.granted
        permitted_map[tc["id"]] = permitted
        if not permitted:
            denied_results[tc["id"]] = "Denied: user rejected this operation"

    _propagate_denials(pending_tcs, permitted_map, denied_results)

    permitted_tcs = [tc for tc in pending_tcs if permitted_map[tc["id"]]]
    results: dict[str, str] = dict(denied_results)
    durations: dict[str, float] = {tc["id"]: 0.0 for tc in pending_tcs}

    levels, _deps = _build_dag_levels(permitted_tcs)
    for level in levels:
        _execute_level(level, results, durations, config)

    for tc in pending_tcs:
        if tc["id"] not in results:
            continue
        if permitted_map[tc["id"]]:
            state.timing_entries.append({"phase": tc["name"], "duration": durations[tc["id"]]})
        state.messages.append({
            "role": "tool", "tool_call_id": tc["id"],
            "name": tc["name"], "content": results[tc["id"]],
        })
        yield ToolEnd(tc["name"], results[tc["id"]], permitted_map[tc["id"]],
                      durations[tc["id"]], tool_id=tc["id"], inputs=tc["input"])


def _resolve_pending_from_state(state):
    """Find unresolved tool_calls from the last assistant msg, or None."""
    if not state.messages:
        return None
    last_asst_idx = next(
        (i for i in range(len(state.messages) - 1, -1, -1)
         if state.messages[i].get("role") == "assistant"),
        None,
    )
    if last_asst_idx is None:
        return []
    last_asst = state.messages[last_asst_idx]
    asst_tcs = last_asst.get("tool_calls") or []
    if not asst_tcs:
        if last_asst_idx == len(state.messages) - 1:
            return None
        return []
    resolved_ids = {
        m.get("tool_call_id") for m in state.messages[last_asst_idx + 1:]
        if m.get("role") == "tool"
    }
    return [tc for tc in asst_tcs if tc["id"] not in resolved_ids]


def _get_bouzecode_commit() -> str:
    try:
        repo_dir = str(Path(__file__).resolve().parent.parent)
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=repo_dir, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except Exception:
        return "unknown"


def _get_bouzecode_version() -> str:
    """Resolve bouzecode version from pyproject.toml [project].version.

    Walks up from this file's directory looking for pyproject.toml.
    Falls back to 'unknown' if the file is not found or unparseable.
    """
    try:
        import tomllib
    except ModuleNotFoundError:
        return "unknown"
    try:
        current = Path(__file__).resolve().parent
        for _ in range(10):  # walk up at most 10 levels
            candidate = current / "pyproject.toml"
            if candidate.is_file():
                with open(candidate, "rb") as f:
                    data = tomllib.load(f)
                version = data.get("project", {}).get("version")
                if version:
                    return version
                return "unknown"
            parent = current.parent
            if parent == current:
                break
            current = parent
    except Exception:
        pass
    return "unknown"


def run(
    user_message: str | None,
    state: AgentState,
    config: dict,
    system_prompt: str,
    depth: int = 0,
    cancel_check=None,
) -> Generator:
    # Cleanup stale _interrupted messages (only the most recent one matters)
    state.messages = [m for m in state.messages if not m.get("_interrupted")]

    if user_message is not None:
        user_msg = {"role": "user", "content": user_message}
        pending_img = config.pop("_pending_image", None)
        if pending_img:
            user_msg["images"] = [pending_img]
        state.messages.append(user_msg)
        state.user_loop_count += 1
        from ..context_manager.methodology import append_user_msg_to_methodology
        append_user_msg_to_methodology(getattr(state, "gc_state", None), user_message)
        yield CheckpointReady(len(state.messages))
    else:
        pending_tcs = _resolve_pending_from_state(state)
        if pending_tcs is None:
            return
        if pending_tcs:
            yield from _complete_pending_tool_calls(pending_tcs, state, config)
            yield CheckpointReady(len(state.messages))

    config = {**config, "_depth": depth, "_system_prompt": system_prompt}
    # Default recover_memory=True for XML-tool models (anthropic/opus/sonnet),
    # False for native-tool models (openrouter/deepseek). Entry points (CLI, web)
    # can override explicitly.
    if "recover_memory" not in config:
        from .providers.registry import model_uses_native_tools
        config["recover_memory"] = not model_uses_native_tools(config.get("model", ""), config)
    from ..agent.loop_detector import ToolCallLoopDetector

    _gc = getattr(state, "gc_state", None)
    config["_gc_state"] = _gc
    # New-model alias: dispatch.py / enforcement_call.py read "_context_state".
    config["_context_state"] = _gc
    config["_state"] = state
    state.system_prompt = system_prompt
    state.bouzecode_commit = _get_bouzecode_commit()
    state.bouzecode_version = _get_bouzecode_version()

    if depth == 0 and state.conversation_start == 0.0:
        state.conversation_start = time.monotonic()

    # Task classification: at depth 0, first user turn only, classify once
    if (
        depth == 0
        and state.user_loop_count == 1
        and "_task_classification_result" not in config
        and config.get("task_classification", True)
        and user_message is not None
    ):
        _classification = classify(user_message, config)
        config["_task_classification_result"] = _classification["type"]
        config["_task_scope_result"] = _classification["scope"]

    ctx = LoopContext(
        required_tool=config.get("required_tool"),
        max_nudges=config.get("max_nudges", 3),
        loop_detector=ToolCallLoopDetector(),
    )

    while True:
        if cancel_check and cancel_check():
            state.close_reason = "cancelled"
            return
        state.turn_count += 1
        ctx.action = TurnAction.PROCEED

        yield from stream_llm_turn(state, config, system_prompt, ctx, cancel_check)
        if ctx.action == TurnAction.BREAK:
            if ctx.interrupted and ctx.assistant_turn:
                state.close_reason = state.close_reason or "cancelled"
                # Persist partial content as ephemeral _interrupted message
                thinking_text = "".join(ctx.thinking_parts)
                text = ctx.assistant_turn.text or ""
                tool_calls_desc = ""
                if ctx.assistant_turn.tool_calls:
                    parts = []
                    for tc in ctx.assistant_turn.tool_calls:
                        parts.append(f"- {tc['name']}({tc.get('input', {})})")
                    tool_calls_desc = "\nTool calls in progress:\n" + "\n".join(parts)
                content_parts = []
                if thinking_text:
                    content_parts.append(f"<thinking>\n{thinking_text}\n</thinking>")
                if text:
                    content_parts.append(text)
                if tool_calls_desc:
                    content_parts.append(tool_calls_desc)
                if content_parts:
                    state.messages.append({
                        "role": "assistant",
                        "content": "\n\n".join(content_parts),
                        "tool_calls": [],
                        "_interrupted": True,
                    })
            return

        if ctx.thinking_overflow:
            # Thinking exceeded limit — save partial thinking, inject nudge, retry
            thinking_text = "".join(ctx.thinking_parts)
            state.messages.append({
                "role": "assistant",
                "content": f"<thinking>\n{thinking_text}\n</thinking>",
                "tool_calls": [],
            })
            nudge = (
                "</thinking>\n\n"
                f"[SYSTEM] Your thinking was cut off after {ctx.thinking_chars} characters.\n\n"
                "You have been analyzing too long without acting. "
                "STOP DELIBERATING. ACT NOW.\n\n"
                "Write a `test_*.py` file to verify the hypotheses you considered above. "
                "Run it. Let the test results guide your next step — "
                "not more thinking."
            )
            state.messages.append({"role": "user", "content": nudge})
            yield CheckpointReady(len(state.messages))
            ctx.thinking_overflow = False
            ctx.thinking_parts = []
            ctx.thinking_chars = 0
            continue

        if ctx.assistant_turn is None:
            state.close_reason = "assistant_none"
            break

        at = ctx.assistant_turn
        remap = uniquify_tool_call_ids(at.tool_calls, state)
        if remap:
            yield ToolIdRemap(remap)

        from .compaction import estimate_tokens
        state.compaction_log.append({
            "event": "llm_call", "timestamp": time.time(), "turn": state.turn_count,
            "api_input_tokens": at.in_tokens, "api_output_tokens": at.out_tokens,
            "api_cache_read": at.cache_read_tokens, "api_cache_create": at.cache_creation_tokens,
            "est_message_tokens": estimate_tokens(_build_messages_for_api(state, config)),
            "message_count": len(state.messages), "has_tool_calls": bool(at.tool_calls),
        })

        content = _build_assistant_content(at.text, ctx.thinking_parts)
        state.messages.append({
            "role": "assistant", "content": content, "tool_calls": at.tool_calls,
        })
        # NB: thinking_parts is NOT cleared here — enforce_methodology (below) needs it
        # to re-inject the model's reasoning into the retry message (assistant <thinking>
        # blocks get stripped from the wire). It is reset at the start of the next turn.
        state.total_input_tokens += at.in_tokens
        state.total_output_tokens += at.out_tokens
        state.total_cache_read_tokens += at.cache_read_tokens
        state.total_cache_creation_tokens += at.cache_creation_tokens
        yield TurnDone(at.in_tokens, at.out_tokens, at.cache_read_tokens,
                       at.cache_creation_tokens)

        if not at.tool_calls:
            action = handle_no_tools(state, config, ctx)
            if action == TurnAction.BREAK:
                yield CheckpointReady(len(state.messages))
                break
            continue

        # Working-memory recovery BEFORE executing this batch (forced side-calls, no
        # in-wire bounce → no loop/duplication). The recovered calls join this batch and
        # execute with it. Methodology (from this turn's thinking) is prepended if absent;
        # Snippets are appended whenever snippetable Read/Skill results remain uncovered
        # (their results are already in — content available).
        meth_recovered = False
        _enforce = config.get("enforce_methodology", True) and not os.environ.get("BOUZECODE_NO_ENFORCE")
        if config.get("recover_memory", False) and _enforce:
            from .enforcement_call import recover_methodology, recover_snippets, snippetable_results
            from .loop_detector import EnforcementWarning, RecoveryFailed
            from ..tools.enforcement_hooks import get_unsnippeted_reads
            if not any(tc["name"] == "Methodology" for tc in at.tool_calls):
                yield EnforcementWarning(missing_tools=["Methodology"])
                # Best-effort: recovery is an optimization — a transient provider
                # error on the side-call must never kill the session.
                try:
                    meth = recover_methodology(state, config, ctx)
                except Exception as exc:
                    yield RecoveryFailed(tool="Methodology", error=str(exc))
                    meth = None
                if meth:
                    meth["id"] = f"methrec_{state.turn_count}"
                    at.tool_calls.insert(0, meth)
                    meth_recovered = True
            if get_unsnippeted_reads(state.messages):
                yield EnforcementWarning(missing_tools=["Snippet"])
                try:
                    snips = recover_snippets(snippetable_results(state.messages), ctx, config, state=state)
                except Exception as exc:
                    yield RecoveryFailed(tool="Snippet", error=str(exc))
                    snips = []
                for i, s in enumerate(snips):
                    s["id"] = f"sniprec_{state.turn_count}_{i}"
                at.tool_calls.extend(snips)
            state.messages[-1]["tool_calls"] = at.tool_calls

        enforce_methodology(at.tool_calls, state, config, ctx)
        # A productive turn re-arms the empty-reply continuation budget: the cap
        # is per empty-streak, not per session (see handle_no_tools).
        ctx.empty_turn_nudges = 0
        ctx.consecutive_no_tool_recoveries = 0

        tool_calls = ctx._final_tool_calls
        yield from execute_tool_calls(tool_calls, state, config, ctx)

        if ctx.action == TurnAction.BREAK:
            break
        if ctx.action == TurnAction.CONTINUE:
            continue

        # A merged Methodology side-call leaves the wire looking like a finished
        # turn (Methodology = the turn-closing meta), and deepseek-v4-pro then
        # deterministically EOSes an empty reply — 3 identical retries, 3 empties
        # (SSE dumps 2026-06-10). A fresh user message unsticks it every time, so
        # say proactively that the turn is still open; this also saves the empty
        # round-trip and its retry cost.
        if meth_recovered:
            state.messages.append({"role": "user", "content": (
                "(System Automated Event): Methodology récupérée et enregistrée "
                "hors-bande. Le tour n'est PAS terminé : continue le travail avec "
                "des tool calls. Si la tâche est entièrement terminée, réponds en "
                "texte SANS aucun tool call."
            )})

        yield CheckpointReady(len(state.messages))

        if ctx.partial_stream:
            state.close_reason = "partial_stream"
            break


def resume_paused(
    pending: dict,
    answer: str,
    state: AgentState,
    config: dict,
    system_prompt: str,
    cancel_check=None,
) -> Generator:
    """Resume a turn paused on AskUserQuestion or WritePlan validation."""
    ask_tc_id = pending["ask_tc_id"]
    pending_tcs = pending.get("pending_tcs", [])
    is_plan_validation = pending.get("is_plan_validation", False)

    if is_plan_validation:
        from ..tools.plan_validation import is_plan_approved
        approved = is_plan_approved(answer)
        if not approved:
            for tc in pending_tcs:
                cancel_msg = f"Cancelled: plan rejected by user \u2014 {answer}"
                state.messages.append({
                    "role": "tool", "tool_call_id": tc["id"],
                    "name": tc["name"], "content": cancel_msg,
                })
                yield ToolEnd(tc["name"], cancel_msg, True, 0.0,
                              tool_id=tc["id"], inputs=tc["input"])
            yield CheckpointReady(len(state.messages))
            yield from run(None, state, config, system_prompt, cancel_check=cancel_check)
            return
        to_run = pending_tcs
    else:
        state.messages.append({
            "role": "tool", "tool_call_id": ask_tc_id,
            "name": "AskUserQuestion", "content": answer,
        })
        from ..context_manager.methodology import append_ask_user_question_to_methodology
        append_ask_user_question_to_methodology(
            getattr(state, "gc_state", None), pending.get("question", ""), answer,
        )
        yield ToolEnd("AskUserQuestion", answer, True, 0.0, tool_id=ask_tc_id,
                      inputs={"question": answer})
        to_run = [tc for tc in pending_tcs if tc["id"] != ask_tc_id]

    if to_run:
        for tc in to_run:
            yield ToolStart(tc["name"], tc["input"], tool_id=tc["id"])

        results: dict[str, str] = {}
        durations: dict[str, float] = {tc["id"]: 0.0 for tc in to_run}
        levels, _deps = _build_dag_levels(to_run)
        for level in levels:
            _execute_level(level, results, durations, config)

        for tc in to_run:
            result = results[tc["id"]]
            state.timing_entries.append({"phase": tc["name"], "duration": durations[tc["id"]]})
            state.messages.append({
                "role": "tool", "tool_call_id": tc["id"],
                "name": tc["name"], "content": result,
            })
            yield ToolEnd(tc["name"], result, True, durations[tc["id"]],
                          tool_id=tc["id"], inputs=tc["input"])

    yield CheckpointReady(len(state.messages))
    yield from run(None, state, config, system_prompt, cancel_check=cancel_check)
