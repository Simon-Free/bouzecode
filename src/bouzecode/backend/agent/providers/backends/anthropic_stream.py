# [desc] Streams responses from the Anthropic API, parsing tool calls from native tool_use blocks or from XML. [/desc]
from __future__ import annotations
import os
import sys
import time
from typing import Generator

from ..types import (
    StreamStarted, TextChunk, ThinkingChunk, ToolCallParsed, AssistantTurn, StreamRestart,
    tentative_ecartee,
)
from ..thinking_level import (
    anthropic_thinking_params, is_masked_refusal, resolve_thinking_level,
    system_for_refusal_retry,
)
from ..conversion import messages_to_anthropic
from .anthropic_client import build_anthropic_client
from .anthropic_native import (
    NativeToolUseAccumulator, messages_to_anthropic_native,
)
from .anthropic_helpers import (
    _create_anthropic_stream_with_retry,
    _install_sse_diagnostic_patch, _iter_stream_resilient,
    _StreamInterrupted,
)
from ..registry import (
    _CONNECTION_RETRY_MAX_ATTEMPTS, _CONNECTION_RETRY_BASE_S,
    _CONNECTION_RETRY_MAX_DELAY_S, PROVIDERS, anthropic_input_includes_cache_write,
)
from ....xml_tool_protocol import XmlToolStreamParser

# Après la fermeture du lot XML on ne LIT plus le texte (le modèle ne doit pas inventer le
# résultat de son propre appel), mais on reste sur le flux le temps de recevoir
# `message_delta` : c'est le SEUL événement qui porte `output_tokens`. Raccrocher tout de
# suite (comportement d'origine) mettait output_tokens à 0 sur CHAQUE tour d'outil — donc sur
# la quasi-totalité des tours en mode XML (mesuré au bac à sable : 0 servi, 102 à 1 771 réels).
# Budget borné : si le modèle continue à écrire, on raccroche et on ESTIME la sortie.
_POST_BATCH_DRAIN_EVENTS = 400
_POST_BATCH_DRAIN_S = 3.0


def _estimate_output_tokens(text: str) -> int:
    """ceil(len / 3.5) : même ratio que l'estimateur du context_viewer (_tokens.py)."""
    return -(-len(text) * 2 // 7) if text else 0


def _truncation_message(cap: int, out_tokens: int, config: dict | None) -> str:
    """Dis QUI a ete tronque, et si relever la config y changerait quelque chose.

    Un side-call (compaction de note, juge, classifieur) ECRASE
    ``config["max_tokens"]`` juste avant d'appeler : lui conseiller de relever la
    config de la session est faux, et laisser croire que le tour de l'agent a ete
    coupe envoie sur une fausse piste (cas vecu : un tour de 2,8K tokens accuse
    d'avoir bute sur un cap de 4096 pose par la compaction).
    """
    label = (config or {}).get("_call_label")
    if not label and (config or {}).get("_depth", 0):
        label = "side-call"
    if label:
        return (
            f"[stream] \u26a0  Anthropic truncated the {label} side-call "
            f"(out_tokens={out_tokens}, cap={cap}). That cap is set by the CALLER "
            f"just before the call, NOT by your session: raising "
            f"config['max_tokens'] will NOT help. The agent turn itself was not cut."
        )
    return (
        f"[stream] \u26a0  Anthropic truncated the response: stop_reason=max_tokens "
        f"(out_tokens={out_tokens}, cap={cap}). "
        f"Raise config['max_tokens'] to let it finish."
    )


def stream_anthropic(
    api_key: str,
    model: str,
    system: str | list,
    messages: list,
    tool_schemas: list,
    config: dict,
    *,
    base_url: str | None = None,
    meth_delta: str = "",
    cache_last: bool = True,
    native_tools: list | None = None,
) -> Generator:
    """Stream from Anthropic.

    With `native_tools`, schemas go through the API `tools` param and tool calls are
    read from native `tool_use` SSE blocks. Without it, tools are documented in the
    prompt and calls are parsed from XML in the text stream (see xml_tool_protocol/).
    The gateway serves both; see docs/investigations/gateway_native_tool_use_retest.md.
    """
    _install_sse_diagnostic_patch()
    from bouzecode.backend.agent.providers.llm_proxy import proxy_headers

    # En-têtes X-Demo-* seulement vers le proxy demo : hors proxy l'appel reste à deux
    # arguments, inchangé.
    extra_headers = proxy_headers(base_url, config)
    if extra_headers:
        client = build_anthropic_client(api_key, base_url, default_headers=extra_headers)
    else:
        client = build_anthropic_client(api_key, base_url)
    native = bool(native_tools)

    wire_messages = (
        messages_to_anthropic_native(messages, cache_last=cache_last) if native
        else messages_to_anthropic(messages, cache_last=cache_last, meth_delta=meth_delta)
    )
    kwargs = {
        "model":      model,
        "max_tokens": config.get("max_tokens", 8192),
        "system":     system,
        "messages":   wire_messages,
    }
    if native:
        kwargs["tools"] = native_tools
    # XML protocol: NO API stop sequence. Asking the API to stop on the literal
    # closing tag cut generation wherever that literal appeared — including inside
    # a param, a CDATA or a test quoting the protocol — leaving the param unclosed
    # and the turn unusable. The batch end is now detected CLIENT-side by the
    # parser (XmlToolStreamParser.batch_closed, top level only) and we hang up
    # ourselves, which keeps the same guarantee: the model cannot go on to invent
    # the result of its own call.
    # Thinking NATIF, réglé par un seul niveau (voir thinking_level). Le thinking manuel
    # en texte déclenchait le classifieur de refus de claude-opus-5 (2026-09-29).
    kwargs.update(anthropic_thinking_params(model, resolve_thinking_level(config)))
    # Only send the 1h-TTL beta header when at least one cache_control actually
    # asks for it — gateways like the internal LLM gateway reject the flag otherwise.
    uses_1h_cache_ttl = isinstance(system, list) and any(
        (block.get("cache_control") or {}).get("ttl") == "1h"
        for block in system if isinstance(block, dict)
    )
    if uses_1h_cache_ttl:
        kwargs["extra_headers"] = {
            "anthropic-beta": "extended-cache-ttl-2025-04-11",
        }
    def _warn(m):
        banner = "\r\x1b[2K\x1b[1;41;97m" + m + "\x1b[0m"
        print(banner, file=sys.stderr, flush=True)

    # Convention unique (registry.anthropic_input_includes_cache_write) : in_tokens compte
    # l'écriture de cache. L'API officielle l'exclut de `input_tokens` : on l'y remet.
    _base_url = os.environ.get("ANTHROPIC_BASE_URL") or PROVIDERS["anthropic"].get("base_url")
    _add_cache_write = not anthropic_input_includes_cache_write(_base_url)

    def _canonical_in(raw_in: int, cache_write: int) -> int:
        # Une entrée brute INFÉRIEURE à l'écriture ne peut pas l'inclure, quoi qu'annonce la
        # convention de l'hôte : mesuré le 2026-09-29, le gateway exclut l'écriture (907 contre
        # 16 247 à froid) — sans ce garde, l'écriture disparaissait et le TUI lisait
        # « +-15K fresh ».
        return raw_in + cache_write if _add_cache_write or raw_in < cache_write else raw_in

    mid_stream_attempts = 0
    # Usage des tentatives abandonnées sur coupure en vol : elles ont été FACTURÉES
    # (prompt lu, début de réponse généré), on les ajoute au tour au lieu de les perdre.
    lost_in = lost_out = lost_cr = lost_cc = 0
    lost_out_estimated = False   # an abandoned attempt's output had to be estimated
    ecartees: list[dict] = []    # les mêmes, une par tentative, pour turns.jsonl
    _stream_started = False
    _had_thinking = False
    _MID_STREAM_MAX_WHEN_THINKING = 2
    # Complétion DÉGÉNÉRÉE : le flux se termine proprement (message_delta reçu) mais
    # rien de substantiel n'a été produit. Ce backend n'avait aucun garde-fou, alors
    # que c'est lui qui sert claude-opus-5 (registry.resolve_provider : tout `claude-*`
    # sans slash -> provider "anthropic"), y compris le modèle par défaut de bouzecode.
    # Le run était donc coupé côté boucle d'agent (loop_turn.handle_no_tools) sans
    # qu'une seule requête n'ait été rejouée. Même budget que côté OpenRouter.
    _EMPTY_COMPLETION_RETRIES = 2
    empty_attempts = 0
    refusal = None
    while True:
        xml_parser = XmlToolStreamParser()
        tool_blocks   = NativeToolUseAccumulator()
        tool_calls    = []
        text          = ""
        # Texte BRUT reçu, avant tout parsing XML : `text` peut être amputé par
        # _drop_orphan_wrapper_suffix (un wrapper orphelin est retiré du transcript),
        # donc il ne dit PAS si le modèle a émis quelque chose. Seul raw_text le dit,
        # et c'est lui qui doit décider d'un retry (mesuré 2026-09-28, claude-opus-5).
        raw_text      = ""
        # Trace bornée des events du stream, écrite SEULEMENT si le tour part à la
        # poubelle (cf. completion_diagnostics) : garder tous les events de toutes les
        # réponses coûterait de la mémoire sur les longues générations, alors que seul
        # un incident a besoin d'être expliqué après coup.
        event_trace: list = []
        _EVENT_TRACE_MAX = 200
        # Texte réellement STREAMÉ (chaque TextChunk yieldé). C'est le seul miroir de
        # ce que la boucle d'agent verra : elle construit ctx.text_parts depuis les
        # TextChunk, PAS depuis turn.text. En mode XML un wrapper <tool_calls>
        # orphelin reste dans turn.text (il attend sa fermeture) alors qu'aucun
        # TextChunk n'est émis : le backend croyait avoir du texte pendant que la
        # boucle voyait un tour vide, et personne ne relançait ni ne signalait rien
        # (mesuré 2026-09-28 sur claude-opus-5).
        streamed_text = ""
        from ..types import UsageSnapshot
        from .completion_diagnostics import dump_degenerate_completion
        in_tokens     = 0
        out_tokens    = 0
        cache_read_tokens     = 0
        cache_creation_tokens = 0
        stop_reason   = None
        batch_done    = False
        drain_events  = 0
        drain_deadline = 0.0
        saw_end       = False   # message_delta / message_stop reached: the stream finished

        stream_ctx = _create_anthropic_stream_with_retry(client, kwargs)
        try:
            with stream_ctx as stream:
                for event in _iter_stream_resilient(stream, _warn):
                    etype = getattr(event, "type", None)
                    # Trace TOUS les etypes (pas seulement les content_block_delta) : un
                    # bloc thinking au texte vide n'émet AUCUN delta, seulement un
                    # content_block_start/stop, et le gateway peut renvoyer un etype inconnu.
                    # Sans cette trace exhaustive, le dump d'un tour dégénéré affichait
                    # events:[] alors que le modèle avait bien produit des blocs
                    # (mesuré 2026-09-28, claude-opus-5, réponses « vides »).
                    if len(event_trace) < _EVENT_TRACE_MAX:
                        _entry = {"type": etype}
                        _blk = getattr(event, "content_block", None)
                        if _blk is not None:
                            _entry["block_type"] = getattr(_blk, "type", None)
                        _dlt = getattr(event, "delta", None)
                        if _dlt is not None:
                            _entry["delta_type"] = getattr(_dlt, "type", None)
                            _dtxt = (getattr(_dlt, "text", None)
                                     or getattr(_dlt, "thinking", None)
                                     or getattr(_dlt, "partial_json", None))
                            if _dtxt:
                                _entry["text"] = str(_dtxt)[:200]
                            _dsr = getattr(_dlt, "stop_reason", None)
                            if _dsr:
                                _entry["stop_reason"] = _dsr
                        event_trace.append(_entry)
                    if batch_done and etype != "message_delta":
                        drain_events += 1
                        if (drain_events > _POST_BATCH_DRAIN_EVENTS
                                or time.monotonic() > drain_deadline):
                            break
                        continue
                    if etype == "message_start":
                        usage = event.message.usage
                        in_tokens = usage.input_tokens
                        cache_read_tokens = getattr(usage, "cache_read_input_tokens", 0) or 0
                        cache_creation_tokens = getattr(usage, "cache_creation_input_tokens", 0) or 0
                        # Surface usage NOW: if the stream dies before its
                        # final AssistantTurn, the loop still knows the cost.
                        yield UsageSnapshot(_canonical_in(in_tokens, cache_creation_tokens),
                                            out_tokens, cache_read_tokens, cache_creation_tokens)
                    elif etype == "content_block_start":
                        if not _stream_started:
                            _stream_started = True
                            yield StreamStarted()
                        block = getattr(event, "content_block", None)
                        if getattr(block, "type", None) == "tool_use":
                            tool_blocks.start(event.index, block.id, block.name)
                    elif etype == "content_block_delta":
                        delta = event.delta
                        dtype = getattr(delta, "type", None)
                        if dtype == "input_json_delta":
                            tool_blocks.delta(event.index, delta.partial_json)
                        elif dtype == "text_delta":
                            raw_text += delta.text
                            if native:
                                text += delta.text
                                streamed_text += delta.text
                                yield TextChunk(delta.text)
                            else:
                                items = xml_parser.feed(delta.text)
                                text += xml_parser.history_delta
                                for item in items:
                                    if isinstance(item, str):
                                        streamed_text += item
                                        yield TextChunk(item)
                                    else:
                                        yield ToolCallParsed(item["name"], item["input"], item["id"])
                                        tool_calls.append(item)
                                if xml_parser.batch_closed:
                                    # Batch closed at top level: stop READING the text
                                    # (the model must not write past its own call), but
                                    # wait for message_delta, which carries output_tokens.
                                    batch_done = True
                                    drain_deadline = time.monotonic() + _POST_BATCH_DRAIN_S
                        elif dtype == "thinking_delta":
                            _had_thinking = True
                            yield ThinkingChunk(delta.thinking)
                    elif etype == "content_block_stop":
                        finished = tool_blocks.stop(event.index)
                        if finished:
                            yield ToolCallParsed(finished["name"], finished["input"],
                                                 finished["id"])
                            tool_calls.append(finished)
                    elif etype == "message_delta":
                        delta_usage = event.usage
                        out_tokens = delta_usage.output_tokens
                        delta_in = getattr(delta_usage, "input_tokens", 0) or 0
                        if delta_in and not in_tokens:
                            in_tokens = delta_in
                        delta_cr = getattr(delta_usage, "cache_read_input_tokens", 0) or 0
                        if delta_cr and not cache_read_tokens:
                            cache_read_tokens = delta_cr
                        delta_cc = getattr(delta_usage, "cache_creation_input_tokens", 0) or 0
                        if delta_cc and not cache_creation_tokens:
                            cache_creation_tokens = delta_cc
                        saw_end = True
                        stop_reason = getattr(event.delta, "stop_reason", None) or stop_reason
                        yield UsageSnapshot(_canonical_in(in_tokens, cache_creation_tokens),
                                            out_tokens, cache_read_tokens, cache_creation_tokens)
                        if batch_done:
                            break
                    elif etype == "message_stop":
                        saw_end = True
                if not saw_end and not batch_done:
                    # EOF without message_delta/message_stop: the connection was cut, the
                    # reply is incomplete. Same handling as any mid-stream drop: retry.
                    raise _StreamInterrupted("stream ended before message_delta")
            # Un REFUS est déterministe : rejouer la même requête rendrait le même
            # refus. On sort sans retry et on le REMONTE, pour que la boucle d'agent
            # ferme sur une raison explicite (content_refusal) au lieu de consommer
            # ses relances pour rien.
            if stop_reason in ("refusal", "content_filter"):
                refusal = refusal or True
                break
            # `text.strip()` et non `text` : une réponse réduite à deux espaces suffisait
            # à passer pour substantielle ici alors que la boucle d'agent, qui strippe,
            # la voyait vide — les deux couches doivent s'accorder sur ce qu'est « vide ».
            if streamed_text.strip() or tool_calls or _had_thinking:
                break
            # Rien n'a été RETENU. Deux situations radicalement différentes :
            #  - raw_text vide : le modèle n'a vraiment rien émis => glitch d'endpoint,
            #    aléatoire, rejouer la requête peut marcher.
            #  - raw_text non vide : le modèle a parlé, mais le protocole a tout écarté
            #    (wrapper <tool_calls> orphelin, <thinking> seul...). C'est DÉTERMINISTE
            #    (mesuré 2026-09-28 sur claude-opus-5 : 3 tours x 3 tentatives, toutes
            #    vides) : rejouer à l'identique redonne la même chose, et chaque
            #    tentative est facturée. On sort et on REMONTE ce qui a été écarté, pour
            #    que la boucle d'agent nudge — seul geste qui débloque réellement.
            if raw_text.strip():
                discarded = raw_text.strip()[:400]
                _dumped = dump_degenerate_completion(
                    reason="protocol_discarded", model=model, provider="anthropic",
                    stop_reason=stop_reason, raw_text=raw_text,
                    streamed_text=streamed_text, tool_calls=tool_calls,
                    usage={"in": in_tokens, "out": out_tokens,
                           "cache_read": cache_read_tokens,
                           "cache_creation": cache_creation_tokens},
                    events=event_trace,
                )
                _warn(f"[bouzecode] le modele a emis du texte que le protocole a ecarte "
                      f"(rien de retenu, finish={stop_reason}) ; pas de nouvelle "
                      f"tentative (deterministe). Extrait : {discarded!r}"
                      + (f" — log complet : {_dumped}" if _dumped else ""))
                break
            if is_masked_refusal(stop_reason=stop_reason, produced_text=raw_text,
                                 tool_calls=tool_calls, had_thinking=_had_thinking,
                                 out_tokens=out_tokens):
                _dumped = dump_degenerate_completion(
                    reason="masked_refusal", model=model, provider="anthropic",
                    stop_reason=stop_reason, raw_text=raw_text,
                    streamed_text=streamed_text, tool_calls=tool_calls,
                    usage={"in": in_tokens, "out": out_tokens,
                           "cache_read": cache_read_tokens,
                           "cache_creation": cache_creation_tokens},
                    events=event_trace,
                )
                # Refus PROBABILISTE (12/96 sur le même payload) et sensible au découpage
                # du system : une seule relance, system aplati (0/48 mesuré).
                flat_system = system_for_refusal_retry(kwargs["system"])
                if flat_system is not None:
                    kwargs["system"] = flat_system
                    kwargs.pop("extra_headers", None)
                    lost_in += _canonical_in(in_tokens, cache_creation_tokens)
                    lost_out += out_tokens
                    lost_cr += cache_read_tokens
                    lost_cc += cache_creation_tokens
                    ecartees.append(tentative_ecartee(
                        "refus_masque", _canonical_in(in_tokens, cache_creation_tokens),
                        out_tokens, cache_read_tokens, cache_creation_tokens))
                    _warn("[bouzecode] refus probable du classifieur (end_turn vide) ; "
                          "une relance avec le system aplati en une chaine"
                          + (f" — log : {_dumped}" if _dumped else ""))
                    continue
                refusal = ("refus probable du classifieur de securite, rendu en end_turn "
                           "vide par le proxy (LiteLLM) du gateway")
                _warn(f"[bouzecode] {refusal} , system deja en une chaine ; abandon"
                      + (f" — log complet : {_dumped}" if _dumped else ""))
                break
            if empty_attempts >= _EMPTY_COMPLETION_RETRIES:
                # Budget epuise : le modele a renvoye du vide a chaque tentative. On
                # garde la trace pour que l'incident reste debugable apres coup.
                _dumped = dump_degenerate_completion(
                    reason="empty_completion", model=model, provider="anthropic",
                    stop_reason=stop_reason, raw_text=raw_text,
                    streamed_text=streamed_text, tool_calls=tool_calls,
                    usage={"in": in_tokens, "out": out_tokens,
                           "cache_read": cache_read_tokens,
                           "cache_creation": cache_creation_tokens},
                    events=event_trace,
                )
                if _dumped:
                    _warn(f"[bouzecode] reponse vide apres "
                          f"{_EMPTY_COMPLETION_RETRIES} tentatives ; "
                          f"log complet : {_dumped}")
                break
            empty_attempts += 1
            # La tentative vide a été FACTURÉE (prompt lu, cache écrit) : on la cumule
            # dans les pertes, comme une tentative abandonnée sur coupure en vol.
            lost_in += _canonical_in(in_tokens, cache_creation_tokens)
            lost_out += out_tokens
            lost_cr += cache_read_tokens
            lost_cc += cache_creation_tokens
            ecartees.append(tentative_ecartee(
                "reponse_vide", _canonical_in(in_tokens, cache_creation_tokens), out_tokens,
                cache_read_tokens, cache_creation_tokens))
            _warn(f"[bouzecode] reponse vide du modele (finish={stop_reason}) ; "
                  f"nouvelle tentative {empty_attempts}/{_EMPTY_COMPLETION_RETRIES}")
            continue
        except _StreamInterrupted as exc:
            mid_stream_attempts += 1
            lost_in += _canonical_in(in_tokens, cache_creation_tokens)
            lost_out += out_tokens or _estimate_output_tokens(text)
            lost_out_estimated = lost_out_estimated or (not out_tokens and bool(text))
            lost_cr += cache_read_tokens
            lost_cc += cache_creation_tokens
            ecartees.append(tentative_ecartee(
                "coupure_en_vol", _canonical_in(in_tokens, cache_creation_tokens),
                out_tokens or _estimate_output_tokens(text), cache_read_tokens,
                cache_creation_tokens))
            max_attempts = (
                _MID_STREAM_MAX_WHEN_THINKING if _had_thinking
                else _CONNECTION_RETRY_MAX_ATTEMPTS
            )
            if mid_stream_attempts >= max_attempts:
                _warn(
                    f"[stream] mid-stream retry budget exhausted "
                    f"({mid_stream_attempts} attempts), keeping partial response."
                )
                break
            delay = min(
                _CONNECTION_RETRY_BASE_S * (2 ** (mid_stream_attempts - 1)),
                _CONNECTION_RETRY_MAX_DELAY_S,
            )
            _warn(
                f"\u27f3 mid-stream drop, retrying full request in {delay:.0f}s "
                f"(attempt {mid_stream_attempts}/{max_attempts}); "
                f"partial text discarded, server will re-generate from scratch."
            )
            _stream_started = False
            _had_thinking = False
            time.sleep(delay)
            # La tentative avortée a pu émettre réflexion, texte, appels : ils sont caducs,
            # le serveur régénère tout. Le dire au consommateur, qui les oublie, au lieu de
            # les garder à côté de la nouvelle génération (réflexions en double).
            yield StreamRestart()

    # Blocks the stream never closed: a truncated native block stays localised to
    # its own call, where a truncated XML block used to contaminate visible text.
    _finalized = tool_blocks.finalize() if native else xml_parser.finalize()
    for _tc in _finalized:
        yield ToolCallParsed(_tc["name"], _tc["input"], _tc["id"])
    tool_calls.extend(_finalized)

    if stop_reason == "max_tokens":
        _warn(_truncation_message(kwargs["max_tokens"], out_tokens, config))

    # message_delta jamais reçu (lot fermé puis budget d'attente épuisé, flux coupé) : la
    # sortie a pourtant été générée et facturée. On l'estime depuis le texte reçu plutôt
    # que de servir 0, et on le DIT (out_tokens_estimated) pour que les vues l'affichent.
    out_estimated = False
    if not out_tokens and text:
        out_tokens = _estimate_output_tokens(text)
        out_estimated = True

    turn = AssistantTurn(text, tool_calls,
                         _canonical_in(in_tokens, cache_creation_tokens) + lost_in,
                         out_tokens + lost_out,
                         cache_read_tokens + lost_cr, cache_creation_tokens + lost_cc,
                         stop_reason=stop_reason)
    turn.out_tokens_estimated = out_estimated or lost_out_estimated
    turn.tentatives_ecartees = ecartees
    turn.refusal = refusal
    if not streamed_text.strip() and not tool_calls and raw_text.strip():
        turn.discarded_text = raw_text.strip()[:400]
    # Verdict lu DANS la réponse : refus explicite du modèle (vs glitch/endpoint).
    # La boucle d'agent s'en sert pour ne pas relancer un refus (close_reason
    # "content_refusal").
    turn.refusal = refusal
    yield turn
