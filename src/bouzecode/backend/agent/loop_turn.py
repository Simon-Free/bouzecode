# [desc] Logique d'un tour : streaming LLM, chronométrage, exécution des outils, enforcement. [/desc]
from __future__ import annotations

import json
import re
import sys
import time
from typing import Generator

# A real (swallowed) tool_use emission always carries a name attribute; matching on
# `name=` avoids firing on prose that merely mentions the literal string "<tool_use>".
_SWALLOWED_TOOLUSE_RE = re.compile(r'<tool_use\b[^>]*\bname\s*=')

from ..core.tool_registry import get_tool_schemas, ends_turn as _tool_ends_turn
from .providers import stream, AssistantTurn, TextChunk, ThinkingChunk, ToolCallParsed, StreamStarted, SystemPayload
from .providers import StreamRestart
from .minimal_payload import build_messages_for_api as _build_messages_for_api
from .minimal_payload import message_du_lot
from .thinking_parser import ThinkingStreamParser

from .state import AgentState, ToolStart, ToolEnd, TurnDone, PermissionRequest, CheckpointReady
from .partial_stream import write_partial, clear_partial

# Tools that produce no result worth sending back to the LLM (working-memory meta).
# Defined in close_guard, which also decides what their presence beside a close act
# proves (nothing); re-exported here for the callers that have always read it here.
from .close_guard import META_ONLY_TOOLS  # noqa: E402

# Backstop for a model that keeps writing NEW meta notes without ever working:
# progress-awareness must not turn the anti-loop guard into an unbounded loop.
META_ONLY_HARD_CAP = 8


def meta_batch_signature(tool_calls: list[dict]) -> str:
    """Fingerprint a meta-only batch by its content, not just its shape.

    Bookkeeping turns legitimately look alike (a Methodology note, a run of
    Snippet discards) while carrying different content each time. Comparing the
    inputs tells an agent that is advancing its plan apart from one rewriting
    the same note forever.
    """
    return json.dumps(
        [[tc.get("name"), tc.get("input") or {}] for tc in tool_calls],
        sort_keys=True, default=str,
    )

# La décision de clôture vit dans close_guard.py. Ré-exportée ici parce que des appelants
# (et des tests) l'importent depuis loop_turn depuis toujours.
from .close_guard import (  # noqa: F401
    MAX_CLOSE_REFUSALS,
    _bg_agent_keeps_turn_open,
    _close_over_failed_tool_nudge,
    _close_over_unread_results_nudge,
    _refused_tool_results,
    annexer_au_lot,
    appels_a_relire,
    deja_executes,
    tools_answered_blind,
)

# `_get_paralysis_abort_after` a été SUPPRIMÉ le 2026-07-29. Il lisait
# BOUZECODE_PARALYSIS_ABORT_AFTER et n'avait AUCUN appelant dans src/ ; son seul test
# était skippé au niveau du module. Un seuil configurable que rien ne consulte donne
# l'illusion d'un garde-fou réglable : on croit border la paralysie en posant la variable
# d'environnement, et il ne se passe rien.

# Exploration-only tools: a streak of turns made solely of these means the model
# is reading without ever producing (anti-paralysis nudge below).
READONLY_TOOLS = META_ONLY_TOOLS | {
    "Read", "Glob", "Grep", "Skill", "SkillResearch", "LoadProjectConfig",
    "GetFolderDescription", "WritePlan", "TaskList", "AskUserQuestion",
}
from .dag import _build_dag_levels, _compute_downstream, _execute_level
from .permissions import _check_permission, _permission_desc, _propagate_denials
from .payload_dump import dump_turn_payload
from ..tools.interaction import PausedForInput, is_web_ipc_active
from ..tools.plan_mode import PlanRejected

from .loop_context import LoopContext, TurnAction


# 2026-08-26 — filet de securite du CONSOMMATEUR de stream.
# `anthropic_helpers` porte deja deux deadlines (180 s sur le premier evenement,
# 60 s inter-chunk), mais elles ne couvrent que SA boucle : creation du stream,
# retry interne, autre backend, ou thread worker qui n'atteint jamais son yield
# restaient sans garde. Le consommateur ci-dessous est le point de passage
# OBLIGE de tous les backends : c'est donc ici que vit le filet.
# 300 s est choisi STRICTEMENT au-dessus des deux deadlines du provider pour ne
# jamais court-circuiter un retry legitime : le filet ne se declenche que si ces
# gardes-la n'ont pas fonctionne.
STREAM_STALL_TIMEOUT_S = 300.0


class StreamStalled(RuntimeError):
    """Le provider a cesse d'emettre : aucun evenement depuis la deadline."""


def _stall_timeout_s() -> float:
    """Deadline d'inactivite, relue A CHAQUE APPEL (reglable a chaud, testable).

    `BOUZECODE_STREAM_STALL_TIMEOUT_S` <= 0 ou non numerique => valeur par defaut.
    """
    import os

    raw = (os.environ.get("BOUZECODE_STREAM_STALL_TIMEOUT_S") or "").strip()
    if raw:
        try:
            val = float(raw)
        except ValueError:
            val = 0.0
        if val > 0:
            return val
    return STREAM_STALL_TIMEOUT_S


def _interruptible_iter(gen, cancel_check=None, stall_timeout_s=None):
    import queue
    import threading

    _SENTINEL = object()
    q: queue.Queue = queue.Queue()
    _deadline = stall_timeout_s if stall_timeout_s is not None else _stall_timeout_s()

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

    last_event_at = time.monotonic()

    while True:
        try:
            item = q.get(timeout=0.2)
        except queue.Empty:
            if cancel_check and cancel_check():
                from .loop import _CancelledTurn
                raise _CancelledTurn()
            idle = time.monotonic() - last_event_at
            if _deadline and idle > _deadline:
                # Sans ceci la boucle tourne indefiniment a vide : seule une
                # intervention humaine (cancel_check) en sortait, et la session
                # mourait sans close_reason. Cf. session f10013b4 du 26/08.
                raise StreamStalled(
                    "provider stream stalled: no event for %.0fs (limit %.0fs)"
                    % (idle, _deadline)
                )
            continue
        last_event_at = time.monotonic()
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
    # Sans cette remise à zéro, un tour dont le flux meurt avant `message_start`
    # reprenait l'usage du tour PRÉCÉDENT : ses tokens étaient comptés deux fois.
    ctx.last_usage = None
    ctx.empreinte = None
    clear_partial(config)

    from .overflow_budget import dynamic_overflow_limit
    overflow_limit = dynamic_overflow_limit(state, config)

    try:
        _schemas = get_tool_schemas()
        ctx.turn_tool_schemas = _schemas
        from .stream_interceptor import get_streamer
        _stream = get_streamer()
        # Route manually-emitted <thinking> text (native reasoning OFF) into
        # thinking_parts, exactly as if it were a native ThinkingChunk, so the
        # working-memory recovery (recover_methodology) can read it.
        _tparser = ThinkingStreamParser()
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
                ctx.empreinte = event.empreinte
                if event.messages is not None:
                    ctx.wire_messages = event.messages
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
                    write_partial(
                        config,
                        state.turn_count,
                        "".join(ctx.text_parts),
                        thinking="".join(ctx.thinking_parts),
                        phase="thinking",
                    )
                elif isinstance(event, TextChunk):
                    if first_text_at is None:
                        first_text_at = now
                    for _kind, _txt in _tparser.feed(event.text):
                        if _kind == "thinking":
                            ctx.thinking_parts.append(_txt)
                        else:
                            ctx.text_parts.append(_txt)
                    # Non-native reasoning: <thinking> text is routed into
                    # thinking_parts by the parser, while the assistant body
                    # (including any <tool_use> XML still buffered in the parser)
                    # must stream live. We report phase="thinking" ONLY while the
                    # parser is still inside an unclosed <thinking> block (or a
                    # native thinking-only stream); it flips to "text" as soon as
                    # </thinking> is consumed, so the body/tool_use headers show
                    # up incrementally. The buffered body (pending_body) is fed
                    # to write_partial so the front-end regex matches <tool_use>
                    # names even before the tag is fully closed/emitted.
                    _streaming_text = "".join(ctx.text_parts) + _tparser.pending_body()
                    # Exiting the <thinking> block means the assistant body has
                    # started, even if its first segment is a still-buffered
                    # <tool_use> tag that produced no strippable text yet. So the
                    # phase flips to "text" the moment the parser is no longer
                    # inside a thinking block — never gated on body content.
                    _phase = "thinking" if _tparser.in_thinking else "text"
                    write_partial(
                        config,
                        state.turn_count,
                        _streaming_text,
                        thinking="".join(ctx.thinking_parts),
                        phase=_phase,
                    )
                # Count all output towards overflow (covers both extended + loud modes)
                ctx.thinking_chars += len(event.text)
                if overflow_limit and ctx.thinking_chars > overflow_limit and not ctx.pending_tool_parsed:
                    ctx.thinking_overflow = True
                    yield event
                    break
                yield event
            elif isinstance(event, StreamRestart):
                # Le backend rejoue la requête après une coupure en vol : tout ce que la
                # tentative avortée a produit est caduc. Le garder dupliquait la réflexion
                # dans le message enregistré (session 3db4403a).
                ctx.text_parts = []
                ctx.thinking_parts = []
                ctx.pending_tool_parsed = []
                ctx.thinking_chars = 0
                _tparser = ThinkingStreamParser()
                first_text_at = None
                last_thinking_at = None
                write_partial(config, state.turn_count, "", thinking="", phase="thinking")
                yield event
            elif isinstance(event, ToolCallParsed):
                ctx.pending_tool_parsed.append(event)
                yield event
            elif isinstance(event, AssistantTurn):
                ctx.assistant_turn = event
            else:
                # Mid-stream usage snapshot: remember the latest one so that a
                # stream which crashes (or is interrupted) before its final
                # AssistantTurn still reports the tokens it really consumed
                # instead of a hardcoded 0. Deliberately NOT re-yielded: no
                # downstream consumer knows this event.
                from .providers import UsageSnapshot
                if isinstance(event, UsageSnapshot):
                    ctx.last_usage = event
        # Flush any residual buffered <thinking>/text (e.g. a block not closed
        # by a trailing newline) into the same channels.
        for _kind, _txt in _tparser.finalize():
            if _kind == "thinking":
                ctx.thinking_parts.append(_txt)
            else:
                ctx.text_parts.append(_txt)
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
                in_tokens=getattr(ctx.last_usage, "in_tokens", 0),
                out_tokens=getattr(ctx.last_usage, "out_tokens", 0),
                cache_read_tokens=getattr(ctx.last_usage, "cache_read_tokens", 0),
                cache_creation_tokens=getattr(ctx.last_usage, "cache_creation_tokens", 0),
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
            in_tokens=getattr(ctx.last_usage, "in_tokens", 0),
            out_tokens=getattr(ctx.last_usage, "out_tokens", 0),
            cache_read_tokens=getattr(ctx.last_usage, "cache_read_tokens", 0),
            cache_creation_tokens=getattr(ctx.last_usage, "cache_creation_tokens", 0),
        )
        ctx.partial_stream = True

    clear_partial(config)

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
    #  Session 9d81964e : 7 refus content_filter et 3 rejeux par le modèle de repli étaient
    #  indiscernables dans turns.jsonl (rejeu = même n° de tour, tentatives refusées fondues
    #  dans les compteurs). Chaque appel dit désormais son modèle, s'il est un rejeu de repli,
    #  et le détail des tentatives facturées puis écartées (déjà incluses dans token_counts).
    appel = {"model": config.get("model", "")}
    if config.get("_appel_de_repli"):
        appel["repli_apres_refus"] = True
    #  Session 4b47c33d : tour servi d'emblée par le repli, le principal n'étant plus retenté.
    if config.get("_repli_collant"):
        appel["repli_collant"] = True
    #  Session 28738fd0 : rejeu du tour refusé avec la note compactée (refusal_fallback).
    if config.get("_variante"):
        appel["variante"] = config["_variante"]
    if at is not None and getattr(at, "tentatives_ecartees", None):
        appel["tentatives_ecartees"] = at.tentatives_ecartees
    dump_turn_payload(
        state, config.get("_session_id", ""),
        getattr(ctx, "wire_messages", None) or messages_for_api,
        system_blocks=ctx.system_blocks, token_counts=token_counts, appel=appel,
    )


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
    # CONTENT REFUSAL, distinct from the empty/degenerate completion handled below.
    # The backend already spent its retries on it (flat-system replay, model fallback),
    # so the loop does not nudge again: it closes explicitly, context intact. The backend
    # surfaces it as stop_reason="content_filter" and/or a `refusal` attribute (see
    # openrouter_stream), the only two signals that tell a refusal from a glitch.
    # The refusal is PROBABILISTIC, not deterministic (12/96 on one payload, 2026-09-29;
    # PBI session of 2026-10-06: the same Read refused twice, accepted the third time).
    # The old message claimed « retrying as-is would refuse again: rephrase »: the user
    # pasted it into the chat twice, and the agent took it as an order to change its
    # approach (« one short action at a time ») for the rest of the session.
    _refusal = getattr(at, "refusal", None)
    if getattr(at, "stop_reason", None) == "content_filter" or _refusal:
        state.close_reason = "content_refusal"
        _motif = _refusal if isinstance(_refusal, str) else ""
        state.close_detail = (
            "refus du filtre de contenu du fournisseur sur ce tour — run interrompu, "
            "contexte conservé. Ce blocage est aléatoire : relance (« continue ») ; "
            "s'il se répète, change de modèle."
            + (f" Motif rapporté : {_motif[:300]}" if _motif else "")
        )
        # ASCII only: this stderr can land in a cp1252-redirected file (headless
        # Windows runs), where an accented char would raise UnicodeEncodeError.
        print("[bouzecode] WARNING: the provider's content filter blocked this turn "
              "- run stopped, context kept. The block is random: retry (\"continue\"); "
              "if it repeats, switch model.", file=sys.stderr)
        return TurnAction.BREAK
    if ctx.required_tool and not ctx.required_tool_called and ctx.nudge_count < ctx.max_nudges:
        ctx.nudge_count += 1
        state.messages.append({"role": "user", "content": f"Tu n'as pas appelé {ctx.required_tool}. Tu DOIS appeler {ctx.required_tool} pour terminer."})
        return TurnAction.CONTINUE
    # Swallowed tool_use emission: the model DID emit <tool_use> blocks, but they
    # parsed to zero calls because they sat inside a ``` fence or a <thinking> region
    # (the XML parser treats both as inert visible text — by design, so prose can show
    # example markup). Without this guard the loop reads "text, no tools" and closes
    # prematurely (headless FinalAnswer) or loses the turn. Re-prompt to re-emit raw,
    # capped so a model that keeps malforming still terminates via the paths below.
    _emitted = "".join(ctx.text_parts) + "\n" + "".join(ctx.thinking_parts)
    MAX_SWALLOWED_NUDGES = 3
    if _SWALLOWED_TOOLUSE_RE.search(_emitted) and ctx.swallowed_xml_nudges < MAX_SWALLOWED_NUDGES:
        ctx.swallowed_xml_nudges += 1
        state.messages.append({"role": "user", "content": (
            "(System Automated Event): tu as émis des blocs <tool_use> mais AUCUN n'a "
            "été exécuté — ils étaient à l'intérieur d'une fence ``` ou d'une autre "
            "balise, où le XML est traité comme texte inerte, jamais comme appel "
            "d'outil. Ré-émets MAINTENANT tes tool calls en XML BRUT :\n"
            "- Aucune fence ``` ni backtick autour des <tool_use>.\n"
            "- Aucune syntaxe <tool_use>/<param> à l'intérieur d'une autre balise.\n"
            "- Les <tool_use> directement au niveau racine de ta réponse."
        )})
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
    if totally_empty:
        # A TOTALLY empty completion is its own failure mode, distinct from a
        # "thinking turn with no tool call" (which HAS text and keeps its usual nudge):
        # there is nothing to distill, nothing to act on. Measured 2026-08-26 on
        # claude-opus-5: the model EOSes with output_tokens~0 on some content (refusal
        # or endpoint limit), and the old code let that turn fall through to the
        # recovery / FinalAnswer-nudge paths — >=12 sterile turns closing under the
        # generic `final_answer_never_called`. We keep a SMALL continuation budget
        # (a fresh user message genuinely unsticks some models — deepseek-v4-pro,
        # 2026-06-10) and then TERMINATE explicitly, context intact for inspection or
        # a re-run on another model.
        MAX_EMPTY_STERILE_TURNS = 3
        ctx.sterile_turns += 1
        # L'absence de Methodology au dernier batch ne supprime plus TOUTE relance :
        # mesuré 2026-09-28, un run coupait au TOUT PREMIER appel LLM (aucun batch
        # assistant n'existe encore, donc le prédicat est faux) sans qu'aucune
        # relance soit tentée, alors qu'un message user frais débloque réellement
        # certains modèles. On garde 1 relance dans ce cas, 2 quand il y a une
        # Methodology à laquelle raccrocher le travail.
        _has_meth = _last_batch_has_methodology(state.messages)
        _max_empty_nudges = 2 if _has_meth else 1
        _budget_left = (
            ctx.empty_turn_nudges < _max_empty_nudges
            and ctx.sterile_turns <= MAX_EMPTY_STERILE_TURNS
        )
        if _budget_left:
            ctx.empty_turn_nudges += 1
            # Flag the empty assistant turn so the minimal wire keeps the previous
            # batch live (see minimal_payload._last_asst_with_tools_idx): without it
            # the nudge below rases the context down to a single message.
            if state.messages and state.messages[-1].get("role") == "assistant" \
                    and not state.messages[-1].get("tool_calls"):
                state.messages[-1]["_empty_completion"] = True
            # Ne prétends une Methodology enregistrée que s'il y en a une : sur un
            # premier tour vide, l'ancien texte mentait au modèle.
            _meth_line = ("Ta Methodology du tour précédent est déjà enregistrée. "
                          if _has_meth else "")
            state.messages.append({"role": "user", "content": (
                "(System Automated Event): réponse vide reçue. " + _meth_line +
                "Continue : exécute ton plan avec des tool calls. Si la tâche est "
                "entièrement terminée, réponds en texte SANS aucun tool call."
            )})
            return TurnAction.CONTINUE
        state.close_reason = "empty_completion"
        state.close_detail = (
            "le modèle a renvoyé une réponse vide (texte et outils absents) — run "
            "interrompu ; cause probable : refus de contenu ou limite de l'endpoint ; "
            "contexte conservé pour reprise/inspection."
        )
        # ASCII only: this stderr can land in a cp1252-redirected file (headless
        # Windows runs), where an accented char would raise UnicodeEncodeError and
        # kill the session this guard is meant to close cleanly.
        print("[bouzecode] WARNING: empty completion from the model (no text, no "
              "tools) - run stopped; context kept for inspection or a re-run on "
              "another model.", file=sys.stderr)
        return TurnAction.BREAK
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
            cs = config.get("_context_state")
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
            "Methodology récupérée hors-bande. "
            "Continue : exécute ton plan avec des tool calls. Si la tâche est "
            "entièrement terminée, appelle FinalAnswer."
        )})
        return TurnAction.CONTINUE
    # --- Headless, tour sans tool call : NE PAS coercer une clôture prématurée. ---
    # Un tour de pure réflexion/PLANIFICATION (thinking, sans texte final) ne veut PAS dire que
    # le coder a fini — le forcer à FinalAnswer livrait un diff VIDE sur les grosses tâches (il
    # épuisait sa phase plan avant d'implémenter, cf. RENDER). On le pousse alors à CONTINUER.
    # Un tour de TEXTE final (le modèle conclut) garde, lui, la demande de FinalAnswer légitime.
    # Plafond haut = garde-fou anti-boucle (un modèle qui n'agit jamais finit par clore).
    MAX_FA_NUDGES = 10
    if config.get("close_requires_final_answer"):
        if ctx.final_answer_nudges < MAX_FA_NUDGES:
            ctx.final_answer_nudges += 1
            if _has_thinking and not "".join(ctx.text_parts).strip():
                nudge = (
                    "(System Automated Event): tour de réflexion sans tool call. Si ta tâche "
                    "n'est PAS terminée (code pas encore écrit ni testé), CONTINUE : implémente "
                    "ton plan avec des tool calls (Edit/Write/Bash). N'appelle FinalAnswer QUE "
                    "si le travail est réellement livré (fichiers modifiés + tests verts)."
                )
            else:
                nudge = (
                    "(System Automated Event): En mode headless tu DOIS appeler FinalAnswer "
                    "pour clore la session. Émets un appel FinalAnswer maintenant."
                )
            state.messages.append({"role": "user", "content": nudge})
            return TurnAction.CONTINUE
        state.close_reason = "final_answer_never_called"
        return TurnAction.BREAK
    # Atteint seulement en TUI interactif : tout run non interactif (`-p`, web, Rundeck) pose
    # `close_requires_final_answer` (ui/repl.py) et passe par la relance ci-dessus. Une clôture
    # sur prose est maîtrisée mais ne LIVRE rien (close_reasons : `idle_no_delivery`, rc 4) ;
    # seul FinalAnswer livre.
    state.close_reason = state.close_reason or "text_no_tools"
    return TurnAction.BREAK


def enforce_methodology(tool_calls: list[dict], state: AgentState, config: dict,
                        ctx: LoopContext) -> None:
    """Plain: dedup by id, record, proceed. No in-wire bounce, no stash. Missing
    Methodology/Snippet is recovered by forced side-calls that augment the batch BEFORE
    execution (see loop.run), which can never loop or duplicate."""
    _seen_ids: set[str] = set()
    tool_calls_deduped = [tc for tc in tool_calls
                          if tc["id"] not in _seen_ids and not _seen_ids.add(tc["id"])]

    state.messages[-1]["tool_calls"] = tool_calls_deduped
    state.total_tool_calls += len(tool_calls_deduped)
    ctx.action = TurnAction.PROCEED
    ctx._final_tool_calls = tool_calls_deduped


def _compact_tool_result(tool_name: str, content: str) -> str:
    """Pass tool results through unchanged.

    Edit/Write results used to be stripped of their diff here to save tokens,
    but that meant the post-edit state never survived in context — causing the
    post-edit doubt (re-running a green test) and re-Read amnesia. Edit/Write
    are now file-keyed snippetable (see snippet_wire._FILE_SNIPPET_TOOLS): the
    full diff reaches the wire, listed "A SNIPPETER id: file=<path>" in the turn's
    <harness_notes>, and the model can freeze the edited region like a Read. So no stripping.
    """
    return content


def execute_tool_calls(tool_calls: list[dict], state: AgentState, config: dict,
                       ctx: LoopContext) -> Generator:
    """Run permissions, DAG execution, results reporting."""
    #  Une FinalAnswer sans `answer` reprend la tentative refusée, AVANT tout affichage.
    from .cloture_reprise import reprendre_la_tentative_suspendue
    reprendre_la_tentative_suspendue(tool_calls, config)
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
    #  Ce que le lot a déjà rendu, visible des outils qui jugent le lot lui-même (la porte de
    #  clôture de FinalAnswer recoupe ses preuves avec les appels RÉELS, ceux du lot compris).
    config["_resultats_du_lot"] = results
    #  Outil long (> 4 min 30) : le minuteur de compaction avant expiration du cache, armé à la
    #  fin de l'appel qui a demandé ce lot, court pendant son exécution (compact_precache).
    try:
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
                runnable = [
                    tc for tc in level
                    if tc["id"] not in downstream and tc["name"] != "AskUserQuestion"
                ]
                if runnable:
                    _execute_level(runnable, results, durations, config)
    finally:
        #  Les deux chemins (avec ou sans AskUserQuestion) : le lot fini ne reste pas dans la config.
        config.pop("_resultats_du_lot", None)

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

    # A background sub-agent (Agent tool, web mode, wait=False) was launched this
    # turn: the manager must keep going (launch other Agents / continue its work)
    # WITHOUT the turn-protocol nudging toward FinalAnswer or closing the turn.
    # We pop the flag (reset each turn) and force CONTINUE — unless the manager
    # ALSO explicitly called FinalAnswer in the same batch, which we always honor.
    if _bg_agent_keeps_turn_open(config, tool_calls):
        ctx.action = TurnAction.CONTINUE
        return

    # Post-execution: ends_turn check
    if tool_calls and any(_tool_ends_turn(tc["name"]) for tc in tool_calls):
        # FinalAnswer whose close the validator refused: the refusal feedback is
        # already in the tool_result — keep the session running so the model
        # finishes the missing items and calls FinalAnswer again.
        if config.pop("_final_answer_refused", False):
            #  Le refus vit dans le résultat de FinalAnswer ; les AUTRES outils du lot, eux,
            #  ont tourné. Le dire, sinon le modèle rejoue le lot entier (précision doublée).
            executes = tools_answered_blind(
                tool_calls, {tc["name"] for tc in tool_calls if _tool_ends_turn(tc["name"])})
            if executes:
                annexer_au_lot(state.messages,
                               "(System Automated Event): " + deja_executes(executes))
            ctx.action = TurnAction.CONTINUE
            return
        if ctx.required_tool and not ctx.required_tool_called and ctx.nudge_count < ctx.max_nudges:
            ctx.nudge_count += 1
            state.messages.append(message_du_lot(f"Tu n'as pas appelé {ctx.required_tool}. Tu DOIS appeler {ctx.required_tool} pour terminer."))
            ctx.action = TurnAction.CONTINUE
            return
        ctx.enforcement_retries = 0
        # A close act the turn does not support. Two ways for the answer to rest on
        # something the model never had, checked for EVERY ends_turn tool and not
        # just FinalAnswer — Focus closes with `final_answer`, so anything wired on
        # the name alone left it unguarded (conversation 6e67be34, 2026-08-18):
        #   - the harness REFUSED a tool of the batch: it never ran;
        #   - a tool of the batch RAN but its result is only handed back next turn.
        # Checked BEFORE the deferred branch — a deferred close is a close too.
        # Budget shared with the other refused-close paths; exhausting it still
        # closes, but the close_reason keeps the anomaly instead of looking clean.
        #  Deux clés de l'agent hôte (Focus) : ses préfixes d'échec, ses effets sans lecture.
        refused = _refused_tool_results(tool_calls, results,
                                        tuple(config.get("close_failure_prefixes") or ()))
        ends_turn_names = {tc["name"] for tc in tool_calls if _tool_ends_turn(tc["name"])}
        blind_all = tools_answered_blind(tool_calls, ends_turn_names)
        #  Le ménage réussi (rangement, Chrome éteint, vérification mise en file) n'a rien
        #  à apprendre au modèle : il ne retient pas la clôture (close_guard).
        blind = [] if refused else appels_a_relire(
            tool_calls, ends_turn_names, results, frozenset(config.get("close_ok_tools") or ()))
        if refused or blind:
            if ctx.final_answer_nudges < MAX_CLOSE_REFUSALS:
                ctx.final_answer_nudges += 1
                annexer_au_lot(state.messages, _close_over_failed_tool_nudge(refused, [
                    tc["name"] for tc in tool_calls
                    if tc["name"] in blind_all and tc["name"] not in dict(refused)])
                    if refused else _close_over_unread_results_nudge(blind, results))
                ctx.action = TurnAction.CONTINUE
                return
            state.close_reason = ("final_answer_over_failed_tool" if refused
                                  else "close_over_unread_results")
            ctx.action = TurnAction.BREAK
            return
        # Determine close_reason: FinalAnswer vs other ends_turn tool
        if any(tc["name"] == "FinalAnswer" for tc in tool_calls):
            context_state = config.get("_context_state")
            deferred_queue = getattr(context_state, "deferred_queue", None) if context_state else None
            if deferred_queue:
                final_tc = next(tc for tc in tool_calls if tc["name"] == "FinalAnswer")
                answer = final_tc["input"].get("answer", "")
                state.close_reason = "final_answer_deferred"
                from ..tools.interaction import DeferredChecks, annonce_verifications_differees
                #  Livrée AVANT ses vérifications : la réponse le dit (état, conversation et
                #  exception), le verdict remplacera l'avis à son arrivée. La file est remise
                #  à la suite et vidée : une clôture suivante ne relance pas les mêmes.
                checks = list(deferred_queue)
                deferred_queue.clear()
                annonce = annonce_verifications_differees(checks)
                answer += annonce
                state.final_answer = (state.final_answer or "") + annonce
                for m in reversed(state.messages):
                    if m.get("role") == "tool" and m.get("tool_call_id") == final_tc["id"]:
                        if isinstance(m.get("content"), str):
                            m["content"] += annonce
                        break
                raise DeferredChecks(answer=answer, checks=checks)
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
                state.messages.append(message_du_lot(
                    "(System Automated Event): Ta réponse semble finale mais tu n'as "
                    "pas appelé FinalAnswer. Appelle FinalAnswer(answer=...) pour "
                    "clore proprement la session."
                ))
                ctx.meta_only_continues += 1
                state.meta_only_nudges += 1
                ctx.action = TurnAction.CONTINUE
                return
            # Cap exhausted — force close
            state.close_reason = "final_answer_nudge_exhausted"
            ctx.action = TurnAction.BREAK
            return



        # Headless mode: nudge FinalAnswer instead of meta-only/text close
        if text_closes and config.get("close_requires_final_answer"):
            MAX_FA_NUDGES = 4
            if ctx.final_answer_nudges < MAX_FA_NUDGES:
                ctx.final_answer_nudges += 1
                state.messages.append(message_du_lot(
                    "(System Automated Event): En mode headless tu DOIS appeler FinalAnswer "
                    "pour clore la session. Émets un appel FinalAnswer maintenant."
                ))
                ctx.action = TurnAction.CONTINUE
                return
            state.close_reason = "final_answer_never_called"
            ctx.action = TurnAction.BREAK
            return

        # Only FinalAnswer closes by default (ticket). A meta-only batch with
        # trailing prose used to close immediately for XML models (text_closes) —
        # this fired on the 1st meta-only turn in the TUI while web_v2 (native)
        # never closed, breaking parity. We now let ONLY the anti-loop cap
        # (2 consecutive meta-only turns) close the session; trailing text no
        # longer force-closes. FinalAnswer (handled above) remains the sole
        # explicit close path.
        # Anti-loop cap, progress-aware: what closes a session is a model that
        # keeps re-emitting the SAME meta batch, not one whose bookkeeping turns
        # each carry something new. A run of Snippet discards followed by a
        # fresh plan is an agent working through its checklist; capping it on
        # turn count alone killed real work mid-task (Focus, 2026-07-30: three
        # such turns after reading 7 images closed the session with no answer).
        # META_ONLY_HARD_CAP still bounds a model that writes forever-new notes.
        signature = meta_batch_signature(tool_calls)
        repeating = signature == ctx.meta_only_signature
        ctx.meta_only_signature = signature
        if (repeating and ctx.meta_only_continues >= 2) \
                or ctx.meta_only_continues >= META_ONLY_HARD_CAP:
            state.close_reason = "meta_only_cap"
            ctx.action = TurnAction.BREAK
            return
        ctx.meta_only_continues += 1
        state.meta_only_nudges += 1
        state.messages.append(message_du_lot(
            "(System Automated Event): Methodology enregistrée, mais ce tour n'a "
            "produit ni travail ni réponse finale. Continue : exécute ton plan avec "
            "des tool calls. Si la tâche est entièrement terminée, réponds en texte "
            "SANS aucun tool call."
        ))
        ctx.action = TurnAction.CONTINUE
        return
    ctx.meta_only_continues = 0
    ctx.meta_only_signature = None

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
        state.messages.append(message_du_lot(warning))
        yield LoopWarning(loop_info.cycle_size, loop_info.repeats, loop_info.tools)
        ctx.loop_detector.reset()

    ctx.action = TurnAction.PROCEED
