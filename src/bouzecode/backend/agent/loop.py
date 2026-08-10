# [desc] Main agent loop: orchestrates LLM streaming, tool execution, permissions, and turn management. [/desc]
from __future__ import annotations

import os
import re
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
from ..tools.interaction import PausedForInput, is_web_ipc_active, DeferredChecks
from ..tools.plan_mode import PlanRejected

from .loop_context import LoopContext, TurnAction
from .loop_turn import stream_llm_turn, handle_no_tools, enforce_methodology, execute_tool_calls
from .task_classifier import classify


# Matches inline <thinking>...</thinking> blocks (same shape as
# web_v2.services.message_render_helpers._THINKING_RE). Used to strip any
# thinking tags already inline in at_text before recomposing, so the thinking
# text is never duplicated (once from thinking_parts, once inline).
_THINKING_STRIP_RE = re.compile(r"<thinking>\s*\n?.*?\n?\s*</thinking>", re.DOTALL)


def _build_assistant_content(at_text: str, thinking_parts: list[str]) -> str:
    """Build assistant message content, prepending thinking tags if present.

    at_text may already contain inline <thinking> blocks (non-native providers
    pass the raw model text through). We strip them first so thinking_parts is
    the single canonical source and the block is not rendered twice.
    """
    if not thinking_parts:
        return at_text
    at_text = _THINKING_STRIP_RE.sub("", at_text).strip()
    thinking_text = "".join(thinking_parts)
    if at_text and at_text.strip() != ".":
        return f"<thinking>\n{thinking_text}\n</thinking>\n\n{at_text}"
    return f"<thinking>\n{thinking_text}\n</thinking>"


def _fire_completion(state, config, close_reason: str) -> None:
    """Fire the `on_completion` event on a GRACEFUL close (FinalAnswer or a text
    reply with no tool calls). Runs in the agent's own process, just before it
    hands control back. Non-graceful exits (assistant_none/partial_stream/
    cancelled) never reach here, so they never fire the event."""
    # Stamp the IPC as FINISHED (with close_reason) BEFORE firing on_completion:
    # for governed/profile agents the hook does a BLOCKING http_post (server-side
    # test-gate, up to ~1900s) that can reap/kill this process before it returns.
    # If we waited until run_agent_event_loop's normal exit, the FINISHED write
    # would never happen and reconcile_dead_agents would see IPC=running -> rc=-1
    # (false crash). Doing it here guarantees a graceful close is recorded.
    # ROOT CAUSE FIX: stamp close_reason into the DISK SESSION before anything else.
    # Historically only the IPC state.json carried close_reason on a graceful close,
    # while <agent>.session.json kept close_reason='' (the finished-write in
    # run_agent_event_loop writes a bare turn, and completion.py only http_posts).
    # Classifiers (_returncode_from_session / _reconcile_graceful_close) read the
    # SESSION → they saw an empty close_reason → false crash. Persist it here so a
    # graceful close is ALWAYS recorded on disk, independently of the IPC.
    state.close_reason = close_reason
    session_file = config.get("_session_file")
    if session_file:
        from ..commands.session.session import _save_session_checkpoint
        _save_session_checkpoint(
            state,
            session_file,
            config.get("_session_id"),
            config.get("_session_path"),
            model=config.get("model"),
        )
    finish_cb = config.get("_ipc_finish_cb")
    if finish_cb:
        finish_cb(close_reason)
    from .hooks import pipeline
    from .hooks.context import completion_context
    pipeline.fire("on_completion", completion_context(state, config, close_reason))


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
        append_user_msg_to_methodology(getattr(state, "context_state", None), user_message)
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

    config["_context_state"] = getattr(state, "context_state", None)
    config["_state"] = state
    # Plugin tools persist into a shared `artifacts` list the host must provide.
    # Back it on AgentState so an artifact created by one plugin tool survives
    # across turns and is read back by the plugin's later calls.
    config["artifacts"] = state.artifacts
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
        and config.get("task_classification", False)
        and user_message is not None
    ):
        _classification = classify(user_message, config)
        config["_task_classification_result"] = _classification["type"]
        config["_task_scope_result"] = _classification["scope"]

    # Attribution des sessions : le profil effectif (--profile, ou la classification de
    # tâche à défaut) et le rôle du run (work / validation / merge — deux runs `coder`
    # n'ont pas le même métier) sont posés sur l'état pour être PERSISTÉS dans le JSON
    # de session. Sans ça toute analyse par profil restait heuristique.
    state.profile = str(config.get("_task_classification_result", "") or "")
    state.run_kind = os.environ.get("BOUZECODE_RUN_KIND", "") or ""

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
        config["_turn_count"] = state.turn_count
        # Push the live turn number to the IPC state so web reconcilers see real
        # progress. run_agent_event_loop only writes turn=1 at start/finish, so
        # without this callback a multi-turn web agent stays frozen at turn=1.
        turn_cb = config.get("_ipc_turn_cb")
        if turn_cb:
            turn_cb(state.turn_count)
        ctx.action = TurnAction.PROCEED

        try:
            yield from stream_llm_turn(state, config, system_prompt, ctx, cancel_check)
        except BaseException as exc:
            # A fatal provider error (connection exhausted after all retries, or a
            # non-retryable API status) reaches here when nothing was streamed. It
            # is NOT a graceful close: mark close_reason='api_error' so the disk
            # session records the death cause (runner derives rc!=0, web_v2 reports
            # a crash) instead of looking like a normal finish. Re-raise so the
            # process still exits non-zero.
            import anthropic as _ant
            if isinstance(exc, (_ant.APIConnectionError, _ant.APIStatusError)):
                state.close_reason = "api_error"
                state.close_detail = f"{type(exc).__name__}: {exc}"
            raise
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
            # Thinking exceeded limit — save partial thinking, inject nudge, retry.
            # Include text_parts: in LOUD mode the reasoning streams as visible
            # TextChunk (-> text_parts), not ThinkingChunk (-> thinking_parts).
            # thinking_chars (which triggered the overflow) counts both, so the
            # summary must read both — else loud-mode reasoning is summarized from
            # an empty buffer, summarize_overflow returns None, and the cut
            # conclusions are never persisted to the methodology (the model then
            # re-derives them every turn and loops).
            thinking_text = "".join(ctx.thinking_parts) + "".join(ctx.text_parts)
            # _overflow_cut flags a turn cut mid-analysis with NO tool call: the
            # batch the model was reasoning about (the previous turn's tool_results,
            # e.g. a freshly-fetched BR) is still unfinished. The minimal-wire keeps
            # that batch live across this boundary so the model can ACT on the same
            # material next turn instead of re-fetching it and re-overflowing (loop).
            state.messages.append({
                "role": "assistant",
                "content": f"<thinking>\n{thinking_text}\n</thinking>",
                "tool_calls": [],
                "_overflow_cut": True,
            })
            # Summarize the cut thinking for re-injection (lightweight side-call)
            from .thinking_summary import summarize_overflow
            summary = summarize_overflow(thinking_text, config)

            summary_block = ""
            if summary:
                cs = config.get("_context_state")
                if cs is not None:
                    # Persist into the methodology so the reasoning is durable
                    # working memory, not a one-shot nudge dropped after one turn.
                    from ..context_manager.methodology import (
                        append_overflow_summary_to_methodology,
                    )
                    append_overflow_summary_to_methodology(cs, summary)
                    summary_block = (
                        "[Ton raisonnement coupé a été résumé dans ta Methodology "
                        "(section « Auto-compacted thoughts after overflow »).]\n"
                        "Ne re-déroule pas ce raisonnement : décide et AGIS.\n\n"
                    )
                else:
                    summary_block = (
                        "[Résumé de ton raisonnement coupé au tour précédent]\n"
                        f"{summary}\n\n"
                        "Ne re-déroule pas ce raisonnement : décide et AGIS.\n\n"
                    )
            # Common (agent-agnostic) overflow notice; the domain-specific action
            # tail comes from config so it stays out of the shared loop.
            action_hint = config.get("overflow_action_hint", "")
            nudge = (
                "</thinking>\n\n"
                f"{summary_block}"
                f"[SYSTEM] Your thinking was cut off after {ctx.thinking_chars} characters.\n\n"
                "You have been analyzing too long without acting. "
                "STOP DELIBERATING. ACT NOW."
                + (f"\n\n{action_hint}" if action_hint else "")
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
                _fire_completion(state, config, state.close_reason or "text_no_tools")
                break
            continue

        # Working-memory recovery BEFORE executing this batch (forced side-calls, no
        # in-wire bounce → no loop/duplication). The recovered calls join this batch and
        # execute with it. Methodology (from this turn's thinking) is prepended if absent;
        # Snippets are appended whenever snippetable Read/Skill results remain uncovered
        # (their results are already in — content available).
        meth_recovered = False
        enforced_tools: list[str] = []
        # Capture the tools the model ACTUALLY emitted this turn, BEFORE any
        # out-of-band recovery inserts Methodology/Snippet (L447/L459). Housekeeping
        # meta (Methodology/Snippet) is excluded: a Snippet-only turn is bookkeeping,
        # not work that proves the task advanced. Used to gate the meth_recovered
        # continuation event below — it must fire ONLY when the real batch was empty.
        _real_tool_names = [
            tc["name"] for tc in at.tool_calls
            if tc["name"] not in ("Methodology", "Snippet")
        ]
        _enforce = config.get("enforce_methodology", True) and not os.environ.get("BOUZECODE_NO_ENFORCE")
        if config.get("recover_memory", False) and _enforce:
            from .enforcement_call import recover_methodology, recover_snippets, snippetable_results
            from .loop_detector import EnforcementWarning, RecoveryFailed
            from ..tools.enforcement_hooks import get_unsnippeted_reads
            if not any(tc["name"] == "Methodology" for tc in at.tool_calls):
                yield EnforcementWarning(missing_tools=["Methodology"])
                enforced_tools.append("Methodology")
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
                enforced_tools.append("Snippet")
                try:
                    snips = recover_snippets(snippetable_results(state.messages), ctx, config, state=state)
                except Exception as exc:
                    yield RecoveryFailed(tool="Snippet", error=str(exc))
                    snips = []
                for i, s in enumerate(snips):
                    s["id"] = f"sniprec_{state.turn_count}_{i}"
                at.tool_calls.extend(snips)
            state.messages[-1]["tool_calls"] = at.tool_calls
            if enforced_tools:
                # Persist the enforcement event in the session (debuggable in web_v2)
                # as a dedicated role — NEVER role="user". Inserted BEFORE the current
                # assistant message so state.messages[-1] stays the assistant (L443).
                state.messages.insert(len(state.messages) - 1, {
                    "role": "enforcement",
                    "missing_tools": enforced_tools,
                    "turn": state.turn_count,
                })

        enforce_methodology(at.tool_calls, state, config, ctx)
        # A productive turn re-arms the empty-reply continuation budget: the cap
        # is per empty-streak, not per session (see handle_no_tools).
        ctx.empty_turn_nudges = 0
        ctx.consecutive_no_tool_recoveries = 0
        ctx.swallowed_xml_nudges = 0

        tool_calls = ctx._final_tool_calls
        try:
            yield from execute_tool_calls(tool_calls, state, config, ctx)
        except DeferredChecks:
            # Deferred close: FinalAnswer emitted with a non-empty deferred queue.
            # loop_turn raises DeferredChecks (close_reason "final_answer_deferred")
            # instead of breaking; the repl persists the queue and exits, and the
            # runner drains the checks afterwards. This is STILL a graceful close,
            # so fire on_completion here (final_text = the FinalAnswer, extracted
            # from state.messages) before re-raising. The deferred checks are re-run
            # by the server test-gate anyway, so firing now is safe.
            _fire_completion(state, config, "final_answer_deferred")
            raise

        if ctx.action == TurnAction.BREAK:
            # Graceful close via a turn-ending tool. NOT reached by
            # assistant_none/partial_stream/cancelled, which break/return elsewhere.
            # Honour the close_reason execute_tool_calls stamped: hardcoding
            # "final_answer" here flattened every other graceful close onto it
            # (_fire_completion assigns state.close_reason), so "ends_turn_tool" and
            # "final_answer_over_failed_tool" were silently rewritten to look like a
            # clean FinalAnswer — hiding exactly the anomalies they exist to surface.
            _fire_completion(state, config, state.close_reason or "final_answer")
            break
        if ctx.action == TurnAction.CONTINUE:
            continue

        # A merged Methodology side-call leaves the wire looking like a finished
        # turn (Methodology = the turn-closing meta), and deepseek-v4-pro then
        # deterministically EOSes an empty reply — 3 identical retries, 3 empties
        # (SSE dumps 2026-06-10). A fresh user message unsticks it every time, so
        # say proactively that the turn is still open; this also saves the empty
        # round-trip and its retry cost.
        if meth_recovered and not _real_tool_names:
            # Only when the model's real batch was EMPTY (Methodology merged in as the
            # sole turn-closing meta) — the historical deepseek EOS case. A productive
            # turn (real tools executed) that merely forgot an explicit Methodology must
            # NOT get this "turn not finished" bounce: it already did work.
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
    # The COLD path (--resume-pending) passes a dict from web_pending.load(); the WARM
    # path (repl._resume_paused_warm) passes a live PausedForInput OBJECT. Indexing that
    # object as a dict (pending["ask_tc_id"]) raised
    # `TypeError: 'PausedForInput' object is not subscriptable`, crashing every resume of
    # an agent parked on AskUserQuestion — so "Reprendre" never relaunched. Normalise to a
    # dict here so the rest of the function stays subscript-based for both callers.
    if not isinstance(pending, dict):
        pending = {
            "ask_tc_id": pending.ask_tc_id,
            "pending_tcs": getattr(pending, "pending_tcs", []),
            "is_plan_validation": getattr(pending, "is_plan_validation", False),
            "question": getattr(pending, "question", ""),
        }
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
            getattr(state, "context_state", None), pending.get("question", ""), answer,
        )
        yield ToolEnd("AskUserQuestion", answer, True, 0.0, tool_id=ask_tc_id,
                      inputs={"question": answer})
        to_run = [tc for tc in pending_tcs if tc["id"] != ask_tc_id]

    if to_run:
        results: dict[str, str] = {}
        durations: dict[str, float] = {tc["id"]: 0.0 for tc in to_run}
        levels, deps = _build_dag_levels(to_run)

        # Re-apply the SAME AskUserQuestion pre-emption as execute_tool_calls:
        # the remaining tool_calls may contain further AskUserQuestion calls that
        # must be surfaced to the UI one at a time (not executed straight through).
        next_ask = None
        if is_web_ipc_active():
            next_ask = next(
                (tc for tc in to_run if tc["name"] == "AskUserQuestion"), None,
            )

        _on_ask_user = config.get("_on_ask_user")

        def _parse_opts(ask_tc):
            raw_opts = ask_tc["input"].get("options")
            if isinstance(raw_opts, str):
                import json as _json
                try:
                    return _json.loads(raw_opts)
                except (ValueError, TypeError):
                    return None
            return raw_opts

        if next_ask is not None and _on_ask_user is not None:
            # Headless/test mode: auto-answer every remaining AskUserQuestion in a
            # loop instead of pausing, so downstream tool_calls become runnable.
            answered = True
            while answered:
                answered = False
                for tc in to_run:
                    if tc["id"] in results:
                        continue
                    if tc["name"] == "AskUserQuestion":
                        results[tc["id"]] = _on_ask_user(
                            tc["input"].get("question", ""), _parse_opts(tc),
                        )
                        answered = True
            # Run any non-Ask tool_calls now that no pause is needed.
            for level in levels:
                runnable = [tc for tc in level if tc["id"] not in results]
                if runnable:
                    _execute_level(runnable, results, durations, config)
        elif next_ask is not None:
            # Web IPC, no auto-answer: run only the tool_calls that do NOT depend
            # on the next AskUserQuestion, then re-pause so the UI surfaces it.
            downstream = _compute_downstream(deps, {next_ask["id"]})
            for level in levels:
                runnable = [
                    tc for tc in level
                    if tc["id"] not in downstream and tc["name"] != "AskUserQuestion"
                ]
                if runnable:
                    _execute_level(runnable, results, durations, config)
        else:
            for level in levels:
                _execute_level(level, results, durations, config)

        # Emit events + persist messages ONLY for tool_calls actually resolved.
        for tc in to_run:
            if tc["id"] not in results:
                continue
            result = results[tc["id"]]
            state.timing_entries.append({"phase": tc["name"], "duration": durations[tc["id"]]})
            state.messages.append({
                "role": "tool", "tool_call_id": tc["id"],
                "name": tc["name"], "content": result,
            })
            yield ToolStart(tc["name"], tc["input"], tool_id=tc["id"])
            yield ToolEnd(tc["name"], result, True, durations[tc["id"]],
                          tool_id=tc["id"], inputs=tc["input"])

        # Still an unanswered AskUserQuestion under web IPC → re-pause completely
        # so repl persists a fresh pending and the next question is surfaced.
        if next_ask is not None and next_ask["id"] not in results:
            raise PausedForInput(
                question=next_ask["input"].get("question", ""),
                options=_parse_opts(next_ask),
                allow_freetext=next_ask["input"].get("allow_freetext", True),
                ask_tc_id=next_ask["id"],
                completed_results=dict(results),
                pending_tcs=[tc for tc in to_run if tc["id"] not in results],
            )

    yield CheckpointReady(len(state.messages))
    yield from run(None, state, config, system_prompt, cancel_check=cancel_check)
