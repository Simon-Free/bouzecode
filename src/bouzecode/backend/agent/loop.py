# [desc] Main agent loop: orchestrates LLM streaming, tool execution, permissions, and turn management. [/desc]
from __future__ import annotations

import os
import re
import subprocess
import sys
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
from ..tools.registration import oublier_micros_de_cloture_refusee

from .loop_context import LoopContext, TurnAction
from .loop_turn import (
    stream_llm_turn, handle_no_tools, enforce_methodology, execute_tool_calls,
    StreamStalled,
)
from .repli_collant import tour_llm
from .task_classifier import classify
from ..context_manager.compact_precache import armer_apres_appel, desarmer_minuteur


# Matches inline <thinking>...</thinking> blocks (same shape as
# web_v2.services.message_render_helpers._THINKING_RE). Used to strip any
# thinking tags already inline in at_text before recomposing, so the thinking
# text is never duplicated (once from thinking_parts, once inline).
_THINKING_STRIP_RE = re.compile(r"<thinking>\s*\n?.*?\n?\s*</thinking>", re.DOTALL)
_UNCLOSED_THINKING_RE = re.compile(r"(?:^|(?<=\n))<thinking>(?:(?!</thinking>).)*\Z", re.DOTALL)

# Plafond de tours ENCHAÎNÉS sans reprise de la main par l'utilisateur.
#
# `while True` (plus bas) ne sort que si le MODÈLE le décide : outil `ends_turn`,
# réponse sans tool call, ou l'un des compteurs de pathologie (meta_only_cap,
# empty_turn_nudges, consecutive_no_tool_recoveries…). Tous ces compteurs bornent des
# tours IMPRODUCTIFS. Un tour qui exécute un vrai outil n'en incrémente aucun : il les
# remet tous à zéro (L490-492). Un modèle — ou un provider — qui rappelle indéfiniment
# un outil productif tient donc la boucle ouverte pour toujours, en brûlant des jetons
# et en immobilisant le worker. C'était le dernier chemin non borné, et rien ne le
# couvrait depuis que l'abort d'anti-paralysie a été retiré (cf. loop_turn.py L51).
#
# Le chiffre : sur les 334 sessions d'agents web réellement exécutées sur ce poste
# (~/.bouzecode/web_agents/*.session.json), la plus longue fait 113 tours, p99 = 72,
# médiane = 6, et AUCUNE ne dépasse 150. 500 laisse donc 4,4× la pire session réelle
# avant de mordre : le plafond ne peut pas interrompre un travail légitime, il ne peut
# attraper qu'un emballement.
#
# Il se compte par APPEL de run(), pas sur la session : ce qu'on borne est la traite
# autonome (l'agent enchaîne sans que personne ne reprenne la main). Un utilisateur qui
# dialogue longtemps en TUI relance un run() à chaque message et repart de zéro.
MAX_AUTONOMOUS_TURNS = 500


def _build_assistant_content(at_text: str, thinking_parts: list[str]) -> str:
    """Build assistant message content, prepending thinking tags if present.

    at_text may already contain inline <thinking> blocks (non-native providers
    pass the raw model text through). We strip them first so thinking_parts is
    the single canonical source and the block is not rendered twice.
    """
    if not thinking_parts:
        return at_text
    at_text = _THINKING_STRIP_RE.sub("", at_text)
    # Un <thinking> resté OUVERT (tour coupé en pleine réflexion) est lui aussi déjà dans
    # thinking_parts : le garder répétait la réflexion (session a3b38124, message 50).
    at_text = _UNCLOSED_THINKING_RE.sub("", at_text).strip()
    thinking_text = "".join(thinking_parts)
    if at_text and at_text.strip() != ".":
        return f"<thinking>\n{thinking_text}\n</thinking>\n\n{at_text}"
    return f"<thinking>\n{thinking_text}\n</thinking>"


#  Comparées par NOM le long du MRO : aucun import dans le qualificateur d'exception.
_COUPURES_DE_TRANSPORT = frozenset({
    "ChunkedEncodingError", "ConnectionError", "ProtocolError", "ReadTimeout", "Timeout",
    "RemoteProtocolError", "ReadError", "IncompleteRead",
})


def coupure_de_transport(exc: BaseException) -> bool:
    """Socket coupé / flux tronqué (requests, urllib3, httpx, http.client) ?"""
    return any(klass.__module__.split(".")[0] in ("requests", "urllib3", "httpx", "http")
               and klass.__name__ in _COUPURES_DE_TRANSPORT for klass in type(exc).__mro__)


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
    #  Les suites déclarées par FinalAnswer ne s'ouvrent qu'ICI, clôture acceptée, et AVANT
    #  le hook (qui peut bloquer puis faire tuer ce process).
    from ..tools.registration import ouvrir_micros_de_cloture_acceptee
    ouvrir_micros_de_cloture_acceptee(config)
    from .cloture_reprise import oublier_la_tentative
    oublier_la_tentative(config)
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
    #  Un agent qui clôt n'a plus besoin des serveurs et watchers que ses Bash ont lancés :
    #  laissés vivants, ils survivaient des heures à l'agent (et à son worktree).
    from ..tools.ops.bash_bg import arreter_processus_lances
    arretes = arreter_processus_lances()
    if arretes:
        print(f"[clôture] processus lancés par Bash arrêtés : {arretes}", flush=True)
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
    """HEAD abrégé du dépôt bouzecode, relu sur le disque à chaque run. Lu dans `.git`
    (quelques fichiers) : le `git rev-parse` d'avant coûtait ~165 ms de spawn par run, 92 %
    du temps d'un test e2e. git ne sert plus que de repli si la lecture directe échoue."""
    from ..core.code_version import REPO_ROOT, read_head_short
    short = read_head_short(REPO_ROOT)
    if short:
        return short
    try:
        repo_dir = str(Path(__file__).resolve().parent.parent)
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=repo_dir, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except Exception:
        return "unknown"


def _stamp_code_version(state: AgentState) -> None:
    """Commit du disque (HEAD relu maintenant) ET commit que ce process a chargé à son
    démarrage : un process vieux de plusieurs jours annonçait le premier alors qu'il
    exécutait le second (sessions du 25/09 à tokens nuls)."""
    from ..core.code_version import BOOT
    state.bouzecode_commit = _get_bouzecode_commit()
    state.bouzecode_version = _get_bouzecode_version()
    state.bouzecode_boot_commit = BOOT.boot_sha
    from ..core.version_session import noter_version
    noter_version(state, version=state.bouzecode_version, commit=state.bouzecode_commit,
                  boot_commit=state.bouzecode_boot_commit)


def _get_bouzecode_version() -> str:
    """Version de bouzecode (pyproject du dépôt, sinon paquet installé)."""
    from ..core.version_session import lire_version_bouzecode
    return lire_version_bouzecode()


def relever_courrier(state: AgentState, config: dict) -> bool:
    """Frontière de tour : les messages écrits PENDANT le lot d'outils qui vient de finir
    entrent maintenant dans la conversation, comme un message de l'utilisateur (et dans la
    note Methodology, comme tout énoncé) — sans attendre la fin du travail, sans rien casser
    du lot : tous ses résultats sont déjà là. `_inbox_pop` n'existe qu'en mode web."""
    relever = config.get("_inbox_pop")
    textes = relever() if relever else []
    if not textes:
        return False
    texte = "\n\n".join(textes)
    from .minimal_payload import message_du_lot
    #  Le lot qui vient de finir reste sur le fil : ce message le SUIT, il ne le clôt pas.
    state.messages.append(message_du_lot(texte))
    state.user_loop_count += 1
    from ..context_manager.methodology import append_user_msg_to_methodology
    append_user_msg_to_methodology(getattr(state, "context_state", None), texte)
    return True


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
        from .demande_en_cours import DEMANDE_UTILISATEUR
        user_msg = {"role": "user", "content": user_message, DEMANDE_UTILISATEUR: True}
        pending_img = config.pop("_pending_image", None)
        if pending_img:
            user_msg["images"] = [pending_img]
        state.messages.append(user_msg)
        state.user_loop_count += 1
        #  Un nouveau message ouvre un tour qui n'est PAS clos : le motif du tour d'avant ne
        #  le décrit plus. Sans ça, un Ctrl+C en plein lot (rien ne réécrit le motif) laissait
        #  la session enregistrée « final_answer » (001c222b) et `close_reason or "cancelled"`
        #  gardait l'ancien. La réponse livrée, elle, reste le dernier livrable de la session.
        state.close_reason = ""
        state.close_detail = ""
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
    # Identité de LA config de cette boucle : un appel annexe (résumé de réflexion,
    # classifieur, rattrapage d'enforcement, compaction) part d'une COPIE de ce dict, donc
    # d'un autre objet — c'est ce qui permet à dispatch.stream de le reconnaître et de
    # journaliser son usage (event "side_call"), sans le confondre avec un appel principal.
    config["_main_config_id"] = id(config)
    # Plugin tools (e.g. demo-pbi-plugin) persist into a shared `artifacts`
    # list the host must provide. Back it on AgentState so a model created by
    # pbi_create_model survives across turns and is read back by pbi_add_table etc.
    config["artifacts"] = state.artifacts
    state.system_prompt = system_prompt
    _stamp_code_version(state)

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

    max_autonomous_turns = config.get("max_turns") or MAX_AUTONOMOUS_TURNS
    turn_count_at_entry = state.turn_count

    while True:
        if cancel_check and cancel_check():
            state.close_reason = "cancelled"
            return
        if state.turn_count - turn_count_at_entry >= max_autonomous_turns:
            # Atteindre ce plafond est une ANOMALIE, jamais une fin de travail : on ne
            # clôt donc pas en silence. `max_turns_exceeded` est classé dans
            # web_v2.close_reasons comme une fin FORCÉE — rc ≠ 0 côté runner, ticket NON
            # avancé côté wake — et la ligne stderr laisse une trace dans le terminal et
            # dans les logs headless, où le close_reason du JSON de session n'est lu par
            # personne. Une boucle qu'on arrête sans le dire, c'est le même bug en moins
            # visible : l'agent rendrait la main comme s'il avait fini.
            state.close_reason = "max_turns_exceeded"
            state.close_detail = (
                f"{max_autonomous_turns} tours enchaînés sans clôture — boucle "
                f"interrompue par le plafond, aucun travail n'est prouvé livré."
            )
            # ASCII pur : cette ligne part aussi dans un stderr redirigé vers un fichier
            # en cp1252 (runs headless Windows), où un emoji lèverait UnicodeEncodeError
            # — le garde-fou tuerait alors la session qu'il est censé clore proprement.
            print(f"[bouzecode] WARNING: {max_autonomous_turns} chained turns without a "
                  f"close - loop stopped by the cap, nothing proven delivered.",
                  file=sys.stderr)
            break
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
            # Refus du modèle (content_filter) : rejeu sur la marche suivante de la chaîne
            # de repli, une tentative par marche (refusal_fallback.py) ; la dernière marche
            # qui a répondu colle (repli_collant.py). Dans le try pour qu'une erreur du
            # rejeu soit qualifiée pareil.
            # 2026-10-12 — un silence du provider (StreamStalled) n'est plus fatal du
            # premier coup : loop_turn ne relaie StreamStalled que si RIEN n'a ete
            # streame (ni texte ni outil), donc rejouer le tour est sans risque. Cas
            # reel : session 69fae8479e09, gateway preprod muet 300 s, session tuee.
            _replay_delays = _stall_replay_delays()
            _replays_done = 0
            #  Un appel au modèle part : le cache va être relu, il n'expirera pas — le minuteur
            #  de compaction avant expiration (armé à la fin de l'appel précédent) tombe.
            desarmer_minuteur(state)
            while True:
                try:
                    yield from tour_llm(state, config, system_prompt, ctx, cancel_check,
                                        stream_turn=stream_llm_turn)
                    break
                except StreamStalled as stall:
                    if _replays_done >= len(_replay_delays):
                        raise
                    # L'appel abandonne a ete facture (prompt lu) : on le compte.
                    _account_llm_call(state, config, ctx)
                    _delay = _replay_delays[_replays_done]
                    _replays_done += 1
                    print(f"[STREAM STALLED] {stall} -- rejeu du tour "
                          f"{_replays_done}/{len(_replay_delays)} dans {_delay:.0f}s",
                          file=sys.stderr)
                    _wait_before_replay(_delay, cancel_check)
        except BaseException as exc:
            # Un appel qui meurt en vol a quand même été facturé (prompt lu) : on le compte.
            _account_llm_call(state, config, ctx)
            # A fatal provider error (connection exhausted after all retries, or a
            # non-retryable API status) reaches here when nothing was streamed. It
            # is NOT a graceful close: mark close_reason='api_error' so the disk
            # session records the death cause (runner derives rc!=0, web_v2 reports
            # a crash) instead of looking like a normal finish. Re-raise so the
            # process still exits non-zero.
            # 2026-08-26 — un provider qui se TAIT en vol (plus aucun evenement de
            # stream, sans erreur ni fin de flux) faisait boucler le consommateur a
            # l'infini : le tour ne revenait jamais, donc aucun garde-fou post-stream
            # ne pouvait s'appliquer et la session mourait avec close_reason='' (cas
            # reel : agent d116c9422334, 3 relances manuelles, 1,06 USD sans livrable).
            # StreamStalled est maintenant levee par _interruptible_iter apres une
            # deadline d'inactivite : on l'estampille explicitement pour que le journal
            # ET l'etat disque DISENT pourquoi le run s'est arrete.
            if isinstance(exc, StreamStalled):
                state.close_reason = "stream_stalled"
                state.close_detail = str(exc)
                print(f"[STREAM STALLED] {exc}", file=sys.stderr)
                raise
            #  Session 9d81964e (2026-10-06) : `ChunkedEncodingError` au 69e tour, relances du
            #  backend épuisées → traceback, process tué, close_reason vide. Une coupure de
            #  TRANSPORT clôt désormais la session proprement, avec sa cause.
            if coupure_de_transport(exc):
                state.close_reason = "api_error"
                state.close_detail = (f"coupure de transport en vol, relances épuisées : "
                                      f"{type(exc).__name__}: {exc}")
                print(f"[TRANSPORT] {state.close_detail}", file=sys.stderr)
                return
            # Ce bloc QUALIFIE une exception deja survenue : il ne doit jamais
            # pouvoir la remplacer par la sienne. Le 2026-08-24, un `import
            # anthropic` place ici a fait mourir des agents sur un
            # ModuleNotFoundError qui n'etait pas la cause premiere, et le
            # diagnostic est parti sur une fausse piste. D'ou : aucun import,
            # aucune resolution de symbole (on compare les noms le long du MRO),
            # et un filet `except BaseException` qui rend la main a l'exception
            # d'origine si le qualificateur defaille pour quelque raison que ce
            # soit.
            try:
                for _klass in type(exc).__mro__:
                    if (
                        _klass.__module__.split(".")[0] == "anthropic"
                        and _klass.__name__ in ("APIConnectionError", "APIStatusError")
                    ):
                        state.close_reason = "api_error"
                        state.close_detail = f"{type(exc).__name__}: {exc}"
                        break
            except BaseException:
                pass
            raise
        # UN SEUL endroit compte l'appel, AVANT les branches (interruption, dépassement de
        # réflexion, tour vide) : chacune rendait la main sans l'avoir compté, et ses tokens
        # manquaient aux totaux de session alors qu'ils avaient été facturés.
        _account_llm_call(state, config, ctx)
        #  Fin de l'appel : le cache du gateway expire dans 5 min. Ce qui suit (lot d'outils,
        #  question à l'utilisateur, attente du message suivant) peut durer plus : à 4 min 30
        #  la note est compactée (context_manager/compact_precache.py).
        armer_apres_appel(config)
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
                    summary_block = " ; résumé dans la Methodology"
                else:
                    summary_block = f" ; résumé :\n{summary}"
            # Pure information, persisted in EVERY later turn (user messages are never
            # dropped from the wire): neutral wording, no `</thinking>` tag, no reasoning
            # vocabulary — measured 2026-09-29, both trip claude-opus-5's refusal classifier.
            # The cut assistant turn is stored closed (`<thinking>…</thinking>`) and stripped
            # from the wire by conversion.py, so nothing is left open to close here.
            nudge = (f"[SYSTEM] Tour précédent interrompu (longueur : {ctx.thinking_chars} "
                     f"caractères){summary_block}")
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

        content = _build_assistant_content(at.text, ctx.thinking_parts)
        state.messages.append({
            "role": "assistant", "content": content, "tool_calls": at.tool_calls,
        })
        # NB: thinking_parts is NOT cleared here — enforce_methodology (below) needs it
        # to re-inject the model's reasoning into the retry message (assistant <thinking>
        # blocks get stripped from the wire). It is reset at the start of the next turn.
        # Bandeau « +N in / +N out » : l'usage COMPTÉ (estimé si l'API ne l'a pas renvoyé),
        # pas le brut de l'AssistantTurn, qui restait à 0 sur un flux coupé avant l'usage.
        compte = ctx.accounted_usage if ctx.accounted_turn == state.turn_count else None
        if compte:
            yield TurnDone(*compte[:4], input_estimated=compte[4], output_estimated=compte[5])
        else:
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
                    meth = recover_methodology(state, config, ctx, at.tool_calls)
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
        ctx.sterile_turns = 0

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
        oublier_micros_de_cloture_refusee(config)
        courrier = relever_courrier(state, config)
        if ctx.action == TurnAction.CONTINUE:
            continue

        # A merged Methodology side-call leaves the wire looking like a finished
        # turn (Methodology = the turn-closing meta), and deepseek-v4-pro then
        # deterministically EOSes an empty reply — 3 identical retries, 3 empties
        # (SSE dumps 2026-06-10). A fresh user message unsticks it every time, so
        # say proactively that the turn is still open; this also saves the empty
        # round-trip and its retry cost.
        if meth_recovered and not _real_tool_names and not courrier:
            # Only when the model's real batch was EMPTY (Methodology merged in as the
            # sole turn-closing meta) — the historical deepseek EOS case. A productive
            # turn (real tools executed) that merely forgot an explicit Methodology must
            # NOT get this "turn not finished" bounce: it already did work.
            from .minimal_payload import message_du_lot
            state.messages.append(message_du_lot(
                "(System Automated Event): Methodology récupérée et enregistrée "
                "hors-bande. Le tour n'est PAS terminé : continue le travail avec "
                "des tool calls. Si la tâche est entièrement terminée, réponds en "
                "texte SANS aucun tool call."
            ))

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

def _usage_of_call(ctx: LoopContext, state: AgentState | None = None):
    """Usage de l'appel qui vient de se terminer : le tour complet s'il existe, sinon le
    dernier instantané du flux (tour coupé par dépassement de réflexion ou par une
    exception avant AssistantTurn). None = aucun octet d'usage reçu, rien à compter."""
    at = ctx.assistant_turn
    if at is not None:
        usage = (at.in_tokens, at.out_tokens, at.cache_read_tokens, at.cache_creation_tokens)
        has_tools, estimated = bool(at.tool_calls), getattr(at, "out_tokens_estimated", False)
    elif ctx.last_usage is not None:
        u = ctx.last_usage
        usage = (u.in_tokens, u.out_tokens, u.cache_read_tokens, u.cache_creation_tokens)
        has_tools, estimated = False, False
    elif ctx.thinking_chars or ctx.pending_tool_parsed:
        # Flux mort (ou coupé par dépassement) avant tout usage, alors que des octets
        # sont arrivés : l'appel a été facturé, on l'estime plutôt que l'oublier.
        usage, has_tools, estimated = (0, 0, 0, 0), bool(ctx.pending_tool_parsed), False
    else:
        return None
    in_tok, out_tok, cache_read, cache_create = usage
    # Flux coupé avant message_delta (dépassement de réflexion, interruption, exception) :
    # la sortie a été générée et facturée ; on l'estime sur les caractères reçus
    # (ctx.thinking_chars compte TOUT le texte et la réflexion) plus les appels d'outils,
    # que le parser ne rend pas en texte, plutôt que servir 0.
    if not out_tok:
        chars = ctx.thinking_chars + _tool_calls_chars(ctx.pending_tool_parsed)
        if chars:
            out_tok, estimated = _chars_to_tokens(chars), True
    # Usage d'entrée jamais reçu (gateway LiteLLM : message_start tout à zéro, l'usage réel
    # n'arrive qu'en fin de flux ; OpenAI-compatible : dernier chunk seulement). Un client
    # qui raccroche avant — fermeture du lot, flux coupé, budget d'attente épuisé — servait
    # 0 : on estime depuis la taille du préfixe envoyé, et on le DIT (in_estimated).
    in_estimated = False
    if not (in_tok or cache_read or cache_create):
        in_tok = _estimate_input_tokens(ctx, state)
        in_estimated = bool(in_tok)
    return in_tok, out_tok, cache_read, cache_create, has_tools, estimated, in_estimated


def _chars_to_tokens(chars: int) -> int:
    """ceil(chars / 3.5) : le ratio de l'estimateur du context_viewer (_tokens.py)."""
    return -(-chars * 2 // 7) if chars > 0 else 0


def _tool_calls_chars(parsed: list) -> int:
    import json as _json
    total = 0
    for ev in parsed or []:
        try:
            total += len(ev.name) + len(_json.dumps(ev.inputs, ensure_ascii=False))
        except (TypeError, ValueError, AttributeError):
            continue
    return total


def _estimate_input_tokens(ctx: LoopContext, state: AgentState | None = None) -> int:
    """Tokens d'entrée estimés depuis ce qui a été ENVOYÉ : longueurs du préfixe relevées
    par l'empreinte (system, outils, note, messages), à défaut blocs système (ou prompt
    système) + messages envoyés."""
    longueurs = (getattr(ctx, "empreinte", None) or {}).get("longueurs") or {}
    chars = sum(v for v in longueurs.values() if isinstance(v, int))
    if not chars:
        import json as _json
        blocks = getattr(ctx, "system_blocks", None) or []
        chars = sum(len(b.get("text", "")) for b in blocks if isinstance(b, dict))
        if not chars and state is not None:
            chars = len(getattr(state, "system_prompt", "") or "")
        envoyes = (getattr(ctx, "wire_messages", None)
                   or getattr(state, "last_api_payload", None) or [])
        try:
            chars += len(_json.dumps(envoyes, ensure_ascii=False, default=str))
        except (TypeError, ValueError):
            pass
    return _chars_to_tokens(chars)


_DEFAULT_STALL_REPLAY_DELAYS_S = "2,5"


def _stall_replay_delays() -> list[float]:
    """Pauses avant chaque rejeu d'un tour coupe par StreamStalled.

    BOUZECODE_STALL_REPLAY_DELAYS_S : liste separee par des virgules (defaut "2,5" = deux
    rejeux) ; chaine vide = aucun rejeu. Une valeur illisible ou negative est ignoree."""
    import os
    raw = os.environ.get("BOUZECODE_STALL_REPLAY_DELAYS_S", _DEFAULT_STALL_REPLAY_DELAYS_S)
    delays: list[float] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            value = float(part)
        except ValueError:
            continue
        if value >= 0:
            delays.append(value)
    return delays


def _wait_before_replay(delay_s: float, cancel_check) -> None:
    """Attend delay_s en restant interruptible par l'humain (cancel_check)."""
    import time
    end = time.monotonic() + delay_s
    while True:
        if cancel_check and cancel_check():
            raise _CancelledTurn()
        remaining = end - time.monotonic()
        if remaining <= 0:
            return
        time.sleep(min(0.2, remaining))


def _account_llm_call(state: AgentState, config: dict, ctx: LoopContext) -> None:
    """Compte UN appel LLM principal, une seule fois : totaux de session + entrée
    `llm_call` du compaction_log (source de /api/sessions/<key>/turns et /costs)."""
    if ctx.accounted_turn == state.turn_count:
        return
    usage = _usage_of_call(ctx, state)
    if usage is None:
        return
    ctx.accounted_turn = state.turn_count
    in_tok, out_tok, cache_read, cache_create, has_tools, estimated, in_estimated = usage
    ctx.accounted_usage = (in_tok, out_tok, cache_read, cache_create, in_estimated, estimated)
    state.total_input_tokens += in_tok
    state.total_output_tokens += out_tok
    state.total_cache_read_tokens += cache_read
    state.total_cache_creation_tokens += cache_create
    from .compaction import estimate_tokens
    entry = {
        "event": "llm_call", "timestamp": time.time(), "turn": state.turn_count,
        "api_input_tokens": in_tok, "api_output_tokens": out_tok,
        "api_cache_read": cache_read, "api_cache_create": cache_create,
        "est_message_tokens": estimate_tokens(_build_messages_for_api(state, config)),
        "message_count": len(state.messages), "has_tool_calls": has_tools,
    }
    if estimated:
        entry["api_output_estimated"] = True
    if in_estimated:
        entry["api_input_estimated"] = True
    if getattr(ctx.assistant_turn, "provider", ""):
        entry["provider"] = ctx.assistant_turn.provider
    from .providers.backends.empreinte import completer
    completer(entry, ctx.empreinte, state)
    state.compaction_log.append(entry)
