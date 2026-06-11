# [desc] <thinking>
# The user wants a single-line description of what loop_turn.py does, under 100 characters.
# </thinking>
# 
# Extracted per-turn logic from the agent loop: LLM streaming, timing, tool execution, enforcement. [/desc]
from __future__ import annotations

import os
import time
from typing import Generator

from ..core.tool_registry import get_tool_schemas, ends_turn as _tool_ends_turn
from .providers import stream, AssistantTurn, TextChunk, ThinkingChunk, ToolCallParsed, StreamStarted, SystemPayload
from .minimal_payload import build_messages_for_api as _build_messages_for_api

from .state import AgentState, ToolStart, ToolEnd, TurnDone, PermissionRequest, CheckpointReady

# Tools that produce no result worth sending back to the LLM (working-memory meta).
META_ONLY_TOOLS = {"Methodology", "Snippet"}


def _get_paralysis_abort_after(config: dict) -> int:
    """Return the paralysis abort threshold.

    Priority: BOUZECODE_PARALYSIS_ABORT_AFTER env var > config dict > default 12.
    Web runner sets env to 0 (disabled) so human-supervised agents are never cut.
    """
    env_val = os.environ.get("BOUZECODE_PARALYSIS_ABORT_AFTER")
    if env_val is not None:
        return int(env_val)
    return int(config.get("paralysis_abort_after", 12))

# Exploration-only tools: a streak of turns made solely of these means the model
# is reading without ever producing (anti-paralysis nudge below).
READONLY_TOOLS = META_ONLY_TOOLS | {
    "Read", "Glob", "Grep", "Skill", "SkillList", "LoadProjectConfig",
    "GetFolderDescription", "WritePlan", "TaskList", "AskUserQuestion",
}
from .dag import _build_dag_levels, _compute_downstream, _execute_level
from .permissions import _check_permission, _permission_desc, _propagate_denials
from .payload_dump import dump_turn_payload
from ..tools.interaction import PausedForInput, is_web_ipc_active
from ..tools.plan_mode import PlanRejected

from .loop_context import LoopContext, TurnAction


def _interruptible_iter(gen, cancel_check=None):
    import queue
    import threading

    _SENTINEL = object()
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
                from .loop import _CancelledTurn
                raise _CancelledTurn()
            continue
        if item is _SENTINEL:
            break
        if isinstance(item, BaseException):
            raise item
        yield item
        # Check cancellation between items for responsive Ctrl+C
        if cancel_check and cancel_check():
            from .loop import _CancelledTurn
            raise _CancelledTurn()


def stream_llm_turn(state: AgentState, config: dict, system_prompt: str,
                    ctx: LoopContext, cancel_check) -> Generator:
    """Stream one LLM call, yield events, populate ctx with results."""
    from .loop import _CancelledTurn

    messages_for_api = _build_messages_for_api(state, config)
    state.last_api_payload = messages_for_api
    dump_turn_payload(state, config.get("_session_id", ""), messages_for_api)

    llm_start = time.monotonic()
    first_event_at: float | None = None
    first_text_at: float | None = None
    last_thinking_at: float | None = None
    ctx.partial_stream = False
    ctx.pending_tool_parsed = []
    ctx.text_parts = []
    ctx.thinking_parts = []
    ctx.thinking_chars = 0
    ctx.assistant_turn = None

    try:
        _schemas = get_tool_schemas()
        ctx.turn_tool_schemas = _schemas
        from .stream_interceptor import get_streamer
        _stream = get_streamer()
        stream_iter = _interruptible_iter(_stream(
            model=config["model"],
            system=system_prompt,
            messages=messages_for_api,
            tool_schemas=_schemas,
            config=config,
        ), cancel_check=cancel_check)
        for event in stream_iter:
            if isinstance(event, SystemPayload):
                ctx.system_blocks = event.system_blocks
                continue
            if isinstance(event, StreamStarted):
                first_event_at = time.monotonic()
                first_text_at = None
                last_thinking_at = None
            elif isinstance(event, (TextChunk, ThinkingChunk)):
                now = time.monotonic()
                if first_event_at is None:
                    first_event_at = now
                if isinstance(event, ThinkingChunk):
                    last_thinking_at = now
                    ctx.thinking_parts.append(event.text)
                elif isinstance(event, TextChunk):
                    if first_text_at is None:
                        first_text_at = now
                    ctx.text_parts.append(event.text)
                # Count all output towards overflow (covers both extended + loud modes)
                ctx.thinking_chars += len(event.text)
                overflow_limit = config.get("thinking_overflow_limit", 20000)
                if overflow_limit and ctx.thinking_chars > overflow_limit and not ctx.pending_tool_parsed:
                    ctx.thinking_overflow = True
                    yield event
                    break
                yield event
            elif isinstance(event, ToolCallParsed):
                ctx.pending_tool_parsed.append(event)
                yield event
            elif isinstance(event, AssistantTurn):
                ctx.assistant_turn = event
    except _CancelledTurn:
        ctx.action = TurnAction.BREAK
        # Build partial turn from whatever was streamed before interruption
        if ctx.pending_tool_parsed or ctx.text_parts or ctx.thinking_parts:
            tool_calls = [
                {"id": ev.tool_id, "name": ev.name, "input": dict(ev.inputs)}
                for ev in ctx.pending_tool_parsed
            ]
            ctx.assistant_turn = AssistantTurn(
                text="".join(ctx.text_parts),
                tool_calls=tool_calls,
                in_tokens=0, out_tokens=0,
                cache_read_tokens=0, cache_creation_tokens=0,
            )
            ctx.partial_stream = True
            ctx.interrupted = True
        return
    except Exception:
        if not ctx.pending_tool_parsed and not ctx.text_parts:
            raise
        tool_calls = [
            {"id": ev.tool_id, "name": ev.name, "input": dict(ev.inputs)}
            for ev in ctx.pending_tool_parsed
        ]
        ctx.assistant_turn = AssistantTurn(
            text="".join(ctx.text_parts),
            tool_calls=tool_calls,
            in_tokens=0, out_tokens=0,
            cache_read_tokens=0, cache_creation_tokens=0,
        )
        ctx.partial_stream = True

    llm_end = time.monotonic()

    # Timing
    ttft = (first_event_at - llm_start) if first_event_at else 0.0
    if first_text_at is not None:
        thinking_dur = max(0.0, first_text_at - (first_event_at or first_text_at))
        streaming_dur = llm_end - first_text_at
    elif last_thinking_at is not None:
        thinking_dur = last_thinking_at - (first_event_at or last_thinking_at)
        streaming_dur = 0.0
    else:
        thinking_dur, streaming_dur = 0.0, llm_end - (first_event_at or llm_start)

    at = ctx.assistant_turn
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

    # Enriched dump with system_blocks and token counts
    token_counts = {
        "in_tokens": at.in_tokens if at else 0,
        "out_tokens": out_tok,
        "cache_read_tokens": cache_read,
        "cache_creation_tokens": cache_create,
    }
    dump_turn_payload(
        state, config.get("_session_id", ""), messages_for_api,
        system_blocks=ctx.system_blocks, token_counts=token_counts,
    )

    if ctx.thinking_parts:
        from .thinking_parser import ThinkingDisciplineMonitor
        monitor = ThinkingDisciplineMonitor()
        violations = monitor.analyze("".join(ctx.thinking_parts))
        if violations:
            state.thinking_log.append({
                "turn": state.turn_count,
                "violations": violations,
            })


def _last_batch_has_methodology(messages: list) -> bool:
    """True if the most recent assistant batch WITH tool calls recorded a Methodology."""
    for m in reversed(messages):
        if m.get("role") == "assistant" and m.get("tool_calls"):
            return any(tc.get("name") == "Methodology" for tc in m["tool_calls"])
    return False


def handle_no_tools(state: AgentState, config: dict, ctx: LoopContext) -> TurnAction:
    """Handle the case where assistant produced no tool_calls."""
    at = ctx.assistant_turn
    if getattr(at, "stop_reason", None) == "max_tokens":
        state.messages.append({"role": "user", "content": "(System Automated Event): Response truncated (max_tokens). Continue where you left off."})
        return TurnAction.CONTINUE
    if ctx.required_tool and not ctx.required_tool_called and ctx.nudge_count < ctx.max_nudges:
        ctx.nudge_count += 1
        state.messages.append({"role": "user", "content": f"Tu n'as pas appelé {ctx.required_tool}. Tu DOIS appeler {ctx.required_tool} pour terminer."})
        return TurnAction.CONTINUE
    # TOTALLY empty reply (no text, no thinking) right after a batch whose
    # Methodology is already recorded (typically the forced recovery side-call):
    # there is nothing to distill, so the compliance bounce below would close the
    # session prematurely. Observed on deepseek-v4-pro (2026-06-10, SSE dumps):
    # the model deterministically EOSes on a wire ending in tool results — the
    # backend retried the identical request 3x and got 3 empty completions, while
    # any fresh user message unsticks it. Nudge continuation instead, capped so a
    # model that keeps replying empty still terminates via the compliance path.
    totally_empty = not "".join(ctx.text_parts).strip() and not ctx.thinking_parts
    if totally_empty and ctx.empty_turn_nudges < 2 and _last_batch_has_methodology(state.messages):
        ctx.empty_turn_nudges += 1
        state.messages.append({"role": "user", "content": (
            "(System Automated Event): réponse vide reçue. Ta Methodology du tour "
            "précédent est déjà enregistrée. Continue : exécute ton plan avec des "
            "tool calls. Si la tâche est entièrement terminée, réponds en texte "
            "SANS aucun tool call."
        )})
        return TurnAction.CONTINUE
    # An empty turn (no tool calls at all) emitted no Methodology — its working
    # memory is silently lost. Out-of-band side-call recovers Methodology from
    # thinking, then a continuation message nudges the model.
    _enforce = config.get("enforce_methodology", True) and not __import__("os").environ.get("BOUZECODE_NO_ENFORCE")
    _has_thinking = bool(ctx.thinking_parts)
    _recover = config.get("recover_memory", False) and _has_thinking and _enforce
    MAX_NO_TOOL_RECOVERIES = 3

    if _recover and ctx.consecutive_no_tool_recoveries < MAX_NO_TOOL_RECOVERIES:
        from .enforcement_call import recover_methodology
        try:
            meth = recover_methodology(state, config, ctx)
        except Exception:
            meth = None
        if meth:
            from ..context_manager.state import METHODOLOGY_NOTE
            meth_content = (meth.get("input") or {}).get("content", "")
            cs = config.get("_context_state") or config.get("_gc_state")
            if cs and meth_content:
                if not hasattr(cs, "notes"):
                    cs.notes = {}
                cs.notes[METHODOLOGY_NOTE] = (
                    cs.notes.get(METHODOLOGY_NOTE, "") + "\n" + meth_content
                )
            meth["id"] = f"methrec_notool_{state.turn_count}"
            if state.messages and state.messages[-1].get("role") == "assistant":
                state.messages[-1].setdefault("tool_calls", []).append(meth)
                state.messages.append({"role": "tool", "tool_call_id": meth["id"],
                                       "content": "OK"})
        ctx.consecutive_no_tool_recoveries += 1
        state.messages.append({"role": "user", "content": (
            "(System Automated Event): NO tool call from your previous turn was recorded. "
            "Methodology récupérée hors-bande depuis ton raisonnement. "
            "Continue : exécute ton plan avec des tool calls. Si la tâche est "
            "entièrement terminée, appelle FinalAnswer."
        )})
        return TurnAction.CONTINUE
    # --- Headless mode: nudge FinalAnswer instead of closing on text-only ---
    MAX_FA_NUDGES = 4
    if config.get("close_requires_final_answer"):
        if ctx.final_answer_nudges < MAX_FA_NUDGES:
            ctx.final_answer_nudges += 1
            state.messages.append({"role": "user", "content": (
                "(System Automated Event): En mode headless tu DOIS appeler FinalAnswer "
                "pour clore la session. Émets un appel FinalAnswer maintenant."
            )})
            return TurnAction.CONTINUE
        state.close_reason = "final_answer_never_called"
        return TurnAction.BREAK
    state.close_reason = state.close_reason or "no_tools_text"
    return TurnAction.BREAK


def enforce_methodology(tool_calls: list[dict], state: AgentState, config: dict,
                        ctx: LoopContext) -> None:
    """Plain: dedup by id, record, proceed. No in-wire bounce, no stash. Missing
    Methodology/Snippet is recovered by forced side-calls that augment the batch BEFORE
    execution (see loop.run), which can never loop or duplicate."""
    _seen_ids: set[str] = set()
    tool_calls_deduped = [tc for tc in tool_calls
                          if tc["id"] not in _seen_ids and not _seen_ids.add(tc["id"])]
    # Compliance turn after a no-tool reply: the bounce says "emit ONLY the
    # missing call(s)". deepseek smuggles work tools in anyway; executing them
    # re-opens the session and the next work turn resets the retry cap →
    # observed endless close→bounce→work cycles (T101 exec run, 5 cycles to
    # timeout). NEW (fix premature close): if the model smuggled productive
    # work alongside meta, KEEP it — the anti-eternal-session cap on
    # compliance_close_deferrals (point 1) prevents infinite cycles instead.
    # Only strip smuggled work when reemit is NOT expected (legacy deepseek
    # safeguard kept for models that cycle without producing).
    if ctx.compliance_turn_pending and not ctx.reemit_expected:
        meta = [tc for tc in tool_calls_deduped if tc["name"] in META_ONLY_TOOLS]
        work = [tc for tc in tool_calls_deduped if tc["name"] not in META_ONLY_TOOLS]
        if meta and work:
            # Smuggled work present: keep everything, mark productive
            ctx.has_productive_turn = True
        elif meta:
            # Only meta: keep just meta (original behavior for pure compliance)
            tool_calls_deduped = meta
    state.messages[-1]["tool_calls"] = tool_calls_deduped
    state.total_tool_calls += len(tool_calls_deduped)
    ctx.action = TurnAction.PROCEED
    ctx._final_tool_calls = tool_calls_deduped


def _compact_tool_result(tool_name: str, content: str) -> str:
    """Strip diff echo from Edit/Write results to reduce fresh token usage in messages."""
    if content.startswith("Error"):
        return content
    if tool_name == "Edit":
        lines = content.split("\n")
        for line in lines:
            if line.startswith("Changes applied to "):
                filename = line[len("Changes applied to "):].rstrip(":")
                added = sum(1 for l in lines if l.startswith("+") and not l.startswith("+++"))
                removed = sum(1 for l in lines if l.startswith("-") and not l.startswith("---"))
                return f"\u2713 {filename} (+{added}/-{removed} lines)"
        return content
    if tool_name == "Write":
        if content.startswith("Created"):
            return content
        first_line = content.split("\n", 1)[0]
        if "File updated" in first_line:
            return first_line
        return content
    return content


def execute_tool_calls(tool_calls: list[dict], state: AgentState, config: dict,
                       ctx: LoopContext) -> Generator:
    """Run permissions, DAG execution, results reporting."""
    permitted_map: dict[str, bool] = {}
    denied_results: dict[str, str] = {}
    for tc in tool_calls:
        yield ToolStart(tc["name"], tc["input"], tool_id=tc["id"])
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

    plan_validation_triggered = False
    if ask_tc is None:
        try:
            for level in levels:
                _execute_level(level, results, durations, config)
                plan_validation_triggered = config.pop("_plan_needs_validation", False)
                if plan_validation_triggered:
                    break
        except PlanRejected as e:
            for tc in permitted_tcs:
                if tc["id"] not in results:
                    results[tc["id"]] = f"Cancelled: plan rejected by user \u2014 {e.feedback}"
                    durations[tc["id"]] = 0.0
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
        if ctx.required_tool and tc["name"] == ctx.required_tool:
            ctx.required_tool_called = True
        state.messages.append({
            "role": "tool", "tool_call_id": tc["id"],
            "name": tc["name"], "content": _compact_tool_result(tc["name"], result),
        })
        yield ToolEnd(tc["name"], result, permitted_map[tc["id"]],
                      durations[tc["id"]], tool_id=tc["id"], inputs=tc["input"])

    # Plan validation pause
    plan_validation_tc = next(
        (tc for tc in permitted_tcs
         if tc["name"] == "WritePlan"
         and tc["id"] in resolved_ids
         and tc["input"].get("user_validation_required")),
        None,
    )
    if plan_validation_tc is not None and plan_validation_triggered:
        pending_tcs = [tc for tc in tool_calls if tc["id"] not in resolved_ids]
        raise PausedForInput(
            question="Valides-tu ce plan ?",
            options=[
                {"label": "Oui, \u00e7a part", "description": "Approuver et ex\u00e9cuter"},
                {"label": "Non, \u00e7a ne me va pas", "description": "Rejeter et donner du feedback"},
            ],
            allow_freetext=True,
            ask_tc_id=plan_validation_tc["id"],
            completed_results=dict(results),
            pending_tcs=pending_tcs,
            is_plan_validation=True,
        )

    if ask_tc is not None:
        pending_tcs = [tc for tc in tool_calls if tc["id"] not in resolved_ids]
        raw_opts = ask_tc["input"].get("options")
        if isinstance(raw_opts, str):
            import json as _json
            try:
                raw_opts = _json.loads(raw_opts)
            except (ValueError, TypeError):
                raw_opts = None
        # Headless/test mode: auto-answer via callback instead of pausing
        _on_ask_user = config.get("_on_ask_user")
        if _on_ask_user is not None:
            answer = _on_ask_user(ask_tc["input"].get("question", ""), raw_opts)
            # Inject as tool_result so the agent loop continues
            results[ask_tc["id"]] = answer
        else:
            raise PausedForInput(
                question=ask_tc["input"].get("question", ""),
                options=raw_opts,
                allow_freetext=ask_tc["input"].get("allow_freetext", True),
                ask_tc_id=ask_tc["id"],
                completed_results=dict(results),
                pending_tcs=pending_tcs,
            )

    # Post-execution: ends_turn check
    if tool_calls and any(_tool_ends_turn(tc["name"]) for tc in tool_calls):
        # FinalAnswer whose close the validator refused: the refusal feedback is
        # already in the tool_result — keep the session running so the model
        # finishes the missing items and calls FinalAnswer again.
        if config.pop("_final_answer_refused", False):
            ctx.action = TurnAction.CONTINUE
            return
        if ctx.required_tool and not ctx.required_tool_called and ctx.nudge_count < ctx.max_nudges:
            ctx.nudge_count += 1
            state.messages.append({"role": "user", "content": f"Tu n'as pas appelé {ctx.required_tool}. Tu DOIS appeler {ctx.required_tool} pour terminer."})
            ctx.action = TurnAction.CONTINUE
            return
        ctx.enforcement_retries = 0
        # Determine close_reason: FinalAnswer vs other ends_turn tool
        if any(tc["name"] == "FinalAnswer" for tc in tool_calls):
            state.close_reason = "final_answer"
        else:
            state.close_reason = "ends_turn_tool"
        ctx.action = TurnAction.BREAK
        return

    ctx.enforcement_retries = 0

    # Meta-only batch: no useful result to send back to the LLM. For XML-protocol
    # models, final-answer text alongside the meta batch closes the session. For
    # NATIVE tool-calling models (deepseek) text is routinely narration-of-intent
    # ("…puis écrivons le code" — observed killing a session mid-task), so the
    # protocol-native close is a reply WITHOUT tool calls; text never closes a
    # meta-only batch there. The forced compliance turn after an empty reply
    # closes either way, and 2 consecutive nudges cap a stuck model.
    if tool_calls and all(tc["name"] in META_ONLY_TOOLS for tc in tool_calls):
        from .providers.registry import model_uses_native_tools
        was_compliance_turn = ctx.compliance_turn_pending
        ctx.compliance_turn_pending = False
        has_final_text = bool("".join(ctx.text_parts).strip())
        native = model_uses_native_tools(config.get("model", ""), config)

        # --- Point 3: text_closes gated by FinalAnswer availability ---
        # For XML models, text+meta used to close unconditionally. Now: if
        # FinalAnswer is an active tool, nudge the model to call it explicitly
        # (cap 2 nudges, then force-close for termination guarantee).
        # Use the schemas actually passed to the LLM this turn (not the global
        # registry which may differ from what the session exposes).
        final_answer_available = any(
            s.get("name") == "FinalAnswer" for s in ctx.turn_tool_schemas
        )
        text_closes = has_final_text and not native
        if text_closes and final_answer_available and ctx.has_productive_turn:
            if ctx.final_answer_nudges < 2:
                ctx.final_answer_nudges += 1
                state.messages.append({"role": "user", "content": (
                    "(System Automated Event): Ta réponse semble finale mais tu n'as "
                    "pas appelé FinalAnswer. Appelle FinalAnswer(answer=...) pour "
                    "clore proprement la session."
                )})
                ctx.meta_only_continues += 1
                state.meta_only_nudges += 1
                ctx.action = TurnAction.CONTINUE
                return
            # Cap exhausted — force close
            state.close_reason = "final_answer_nudge_exhausted"
            ctx.action = TurnAction.BREAK
            return

        # --- Point 1: compliance_closes gated by productive turn ---
        # reemit_expected : la conformité suit un tour dont l'émission a pu être
        # avalée — ne pas clore dessus, laisser la nudge meta-only relancer le
        # travail (cap meta_only_continues inchangé).
        compliance_closes = was_compliance_turn and not ctx.reemit_expected
        ctx.reemit_expected = False
        if compliance_closes and not ctx.has_productive_turn:
            # No productive work yet — defer close (cap at 2 deferrals)
            if ctx.compliance_close_deferrals < 2:
                ctx.compliance_close_deferrals += 1
                state.messages.append({"role": "user", "content": (
                    "(System Automated Event): Tour de conformité reçu mais aucun "
                    "travail productif n'a encore été exécuté dans cette session. "
                    "Continue : exécute ton plan avec des tool calls de travail "
                    "(Edit, Write, Bash, RunPythonTest…). Si la tâche est terminée, "
                    "appelle FinalAnswer."
                )})
                state.meta_only_nudges += 1
                ctx.action = TurnAction.CONTINUE
                return
            # Cap reached — force close to prevent eternal session
            state.close_reason = "compliance_cap"
            ctx.action = TurnAction.BREAK
            return

        # Headless mode: nudge FinalAnswer instead of meta-only/text close
        if text_closes and config.get("close_requires_final_answer"):
            MAX_FA_NUDGES = 4
            if ctx.final_answer_nudges < MAX_FA_NUDGES:
                ctx.final_answer_nudges += 1
                state.messages.append({"role": "user", "content": (
                    "(System Automated Event): En mode headless tu DOIS appeler FinalAnswer "
                    "pour clore la session. Émets un appel FinalAnswer maintenant."
                )})
                ctx.action = TurnAction.CONTINUE
                return
            state.close_reason = "final_answer_never_called"
            ctx.action = TurnAction.BREAK
            return

        if text_closes or compliance_closes or ctx.meta_only_continues >= 2:
            if text_closes:
                state.close_reason = "meta_only_text_close"
            elif compliance_closes:
                state.close_reason = "compliance_close"
            else:
                state.close_reason = "meta_only_cap"
            ctx.action = TurnAction.BREAK
            return
        ctx.meta_only_continues += 1
        state.meta_only_nudges += 1
        state.messages.append({"role": "user", "content": (
            "(System Automated Event): Methodology enregistrée, mais ce tour n'a "
            "produit ni travail ni réponse finale. Continue : exécute ton plan avec "
            "des tool calls. Si la tâche est entièrement terminée, réponds en texte "
            "SANS aucun tool call."
        )})
        ctx.action = TurnAction.CONTINUE
        return
    ctx.compliance_turn_pending = False
    ctx.reemit_expected = False
    ctx.meta_only_continues = 0

    # Track productive turns: any tool NOT in READONLY_TOOLS marks the session
    # as having done real work (used to gate compliance close in point 1).
    if any(tc["name"] not in READONLY_TOOLS for tc in tool_calls):
        ctx.has_productive_turn = True

    # Track consecutive read-only turns (observability only — no abort/nudge).
    if tool_calls and all(tc["name"] in READONLY_TOOLS for tc in tool_calls):
        ctx.readonly_streak += 1
    else:
        ctx.readonly_streak = 0

    # Loop detection
    ctx.loop_detector.record_turn(tool_calls)
    loop_info = ctx.loop_detector.check()
    if loop_info:
        from .loop_detector import LoopWarning
        warning = (
            f"\u26a0\ufe0f Loop detected: you've repeated the same "
            f"{loop_info.cycle_size}-turn tool call pattern {loop_info.repeats} times "
            f"(tools: {', '.join(loop_info.tools)}). "
            f"Break the cycle \u2014 try a different approach or ask the user for help."
        )
        state.messages.append({"role": "user", "content": warning})
        yield LoopWarning(loop_info.cycle_size, loop_info.repeats, loop_info.tools)
        ctx.loop_detector.reset()

    ctx.action = TurnAction.PROCEED
