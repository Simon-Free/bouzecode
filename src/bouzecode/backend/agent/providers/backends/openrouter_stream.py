# [desc] Streams from OpenRouter via requests, through the corporate NTLM proxy, with XML tool parsing. [/desc]
from __future__ import annotations
import functools
import logging
import os
import time
from typing import Generator

from ..types import (
    StreamStarted, TextChunk, ThinkingChunk, ToolCallParsed, AssistantTurn, StreamRestart,
)
from ..conversion import messages_to_anthropic
from ..registry import OPENROUTER_BASE_URL, model_uses_native_tools
from ....xml_tool_protocol import XmlToolStreamParser
from ....core.tls import requests_verify
from .openrouter_native import (
    tool_schemas_to_openai, messages_to_openai_native, user_content,
    accumulate_tool_call_deltas, finalize_tool_calls,
)
from .openrouter_retry import (
    post_with_retry, transport_errors, UpstreamStreamError, stream_error_message,
)
from . import openrouter_provider
from .tool_choice_policy import resolve_tool_choice
from .stream_progress import (
    ProgressWatchdog, StreamNoProgress, chunk_makes_progress, progress_timeouts,
)
from .content_filter_report import report_content_filter_refusal
from ..types import tentative_ecartee
# _build_session stays a module attribute: tests monkeypatch it at this path.
from .openrouter_transport import build_session as _build_session, iter_sse as _iter_sse

logger = logging.getLogger(__name__)

# Some upstream providers occasionally return a degenerate completion: a single
# chunk with empty content, no reasoning, no tool_calls, finish_reason "stop"
# (observed on deepseek-v4-pro via GMICloud, 2026-06-10). Nothing substantive
# has been yielded at that point, so re-issuing the request is invisible to the
# conversation.
_EMPTY_COMPLETION_RETRIES = 2

# The socket can also die *while* reading the SSE body ("Read timed out"), which
# post_with_retry cannot see. Replaying the whole POST is only safe as long as
# nothing was streamed to the UI yet, so this budget guards that window only.
_STREAM_TIMEOUT_BACKOFFS_S = (2.0, 4.0, 8.0, 16.0, 30.0)

# A chunk `error` mid-stream (upstream overloaded / cut) is replayed even after text
# went out: StreamRestart tells the consumer to drop the aborted attempt. Budget
# exhausted, the chunk is ignored as before and the partial turn is kept.
_STREAM_ERROR_BACKOFFS_S = (2.0, 8.0)

# Aliased as a module global so tests can monkeypatch the wait away.
_sleep = time.sleep


def _system_text(system: str | list) -> str:
    """Flatten the Anthropic system_blocks (list of text blocks) into one string."""
    if isinstance(system, str):
        return system
    parts = [b.get("text", "") for b in system if isinstance(b, dict)]
    return "\n\n".join(p for p in parts if p)


def _content_to_text(content) -> str:
    """OpenRouter wants plain-string content; join any Anthropic text blocks."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            b.get("text", "") for b in content
            if isinstance(b, dict) and b.get("type") == "text"
        )
    return str(content)


def _system_content(system: str | list, model: str) -> str | list:
    """Keep the `cache_control` breakpoints alive on the Anthropic pass-through.

    The gateway serves `claude-*` through LiteLLM in Anthropic pass-through mode
    (and OpenRouter does the same for `anthropic/claude-*`): both forward
    `cache_control` markers when the system is a list of content parts. Flattening
    the blocks into one string dropped every breakpoint, so no prefix was ever
    cached — the status line lost its "cached / cache-write" figures and the whole
    prompt was billed fresh on every single turn.

    Azure/GPT-5 routes reject a structured system content, so they keep the flat
    string: only cache-capable models get the list.
    """
    if isinstance(system, str):
        return system
    blocks = [b for b in system if isinstance(b, dict) and b.get("text")]
    if not (_is_cache_capable(model) and any(b.get("cache_control") for b in blocks)):
        return _system_text(system)
    parts: list[dict] = []
    for b in blocks:
        part: dict = {"type": "text", "text": b["text"]}
        if b.get("cache_control"):
            part["cache_control"] = b["cache_control"]
        parts.append(part)
    return parts


def _note_hors_system(reste: list[dict]) -> str:
    """Note + delta (blocs à cache_control) concaténés sans séparateur — le delta commence déjà
    par le sien, le texte du tour N reste donc un préfixe de celui du tour N+1 —, puis le reste
    (contexte de session, règle finale)."""
    note = "".join(b["text"] for b in reste if b.get("cache_control")).strip("\n")
    suite = "\n\n".join(b["text"] for b in reste if not b.get("cache_control")).strip("\n")
    return "\n\n".join(t for t in (note, suite) if t)


def _messages_natifs(messages: list, system: str | list, model: str, stable_blocks: int) -> list:
    """Messages OpenAI à outils natifs, system strictement stable.

    Le chat template (DeepSeek & co.) sérialise les OUTILS APRÈS le system : tout octet qui
    change dans le system rend les ≈ 7 000 tokens d'outils non cachés, à chaque tour (rapport
    docs/reduction_tokens §0.2 ; essai du 24/09 : « cache raté » presque à chaque tour). Le
    system ne garde donc que les `stable_blocks` premiers blocs (noyau + profil, identiques
    d'un tour à l'autre) ; contexte de session et règle finale passent dans un message user
    placé juste après le premier (celui qui porte la note en <working_notes>, cf. dispatch).
    Claude (liste de blocs à cache_control, outils en tête côté Anthropic) n'est pas concerné."""
    systeme = _system_content(system, model)
    keep_cache = _is_cache_capable(model)
    if not stable_blocks or not isinstance(systeme, str) or isinstance(system, str):
        return messages_to_openai_native(messages, systeme, keep_cache)
    blocs = [b for b in system if isinstance(b, dict) and b.get("text")]
    out = messages_to_openai_native(messages, _system_text(blocs[:stable_blocks]), keep_cache)
    reste = _note_hors_system(blocs[stable_blocks:])
    if not reste:
        return out
    apres = 2 if len(out) > 1 and out[1]["role"] == "user" else 1
    return out[:apres] + [{"role": "user", "content": reste}] + out[apres:]


def _is_cache_capable(model: str) -> bool:
    """Claude sur une route OpenAI-compatible (LiteLLM du gateway, OpenRouter) : les
    `cache_control` des parties de contenu sont transmis ; Azure/GPT-5 refuse ces parties."""
    return "claude" in model.lower()


def _messages_to_openai(messages: list, system: str | list, model: str = "") -> list:
    """Reuse the XML tool serialization, then flatten to OpenAI string content."""
    converted = messages_to_anthropic(messages, cache_last=False)
    oai = [{"role": "system", "content": system}]
    for m in converted:
        content = (user_content(m["content"], _is_cache_capable(model)) if m["role"] == "user"
                   else _content_to_text(m["content"]))
        oai.append({"role": m["role"], "content": content})
    return oai


def _usage_tokens(usage: dict) -> tuple[int, int, int, int]:
    """``(in, out, cache read, cache write)`` from either usage convention, ``in`` being the
    prompt NOT read from cache (cache write included) — the chain-wide convention.

    This endpoint is not always OpenAI: the internal LLM gateway serves `claude-*` through a
    LiteLLM pass-through that reports Anthropic's own field names. Reading only
    `prompt_tokens_details.cached_tokens` made every cache figure read zero for those
    models — cache write was even hardcoded to 0 — so the status line silently dropped
    "cached / cache-write" and the run looked cheaper than it billed.

    The two conventions also disagree on what the input count contains: OpenAI's
    `prompt_tokens` INCLUDES the cached prefix, Anthropic's `input_tokens` EXCLUDES it.
    We take the fresh part (subtracting only when the total is big enough to actually hold
    the cached part), then add the cache WRITE back: the chain counts it in `in`.
    """
    cache_read = int(usage.get("cache_read_input_tokens") or 0)
    cache_write = int(usage.get("cache_creation_input_tokens") or 0)
    if not cache_read:
        details = usage.get("prompt_tokens_details") or {}
        cache_read = int(details.get("cached_tokens") or 0)

    total_in = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
    out = int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)

    cached = cache_read + cache_write
    fresh_in = total_in - cached if total_in >= cached else total_in
    # Convention unique de la chaîne (registry.anthropic_input_includes_cache_write) :
    # in = prompt NON lu en cache, écriture de cache COMPRISE. Rendre le seul « frais »
    # faisait retirer une SECONDE fois l'écriture dans calc_cost (in - cache_write).
    return max(fresh_in, 0) + cache_write, out, cache_read, cache_write


# Chunks we keep reading AFTER the tool-call batch closed, purely to catch the
# trailing usage-only chunk. A compliant stream sends it within one or two
# chunks; the cap stops a model that keeps generating past </tool_calls> from
# holding the turn open.
_POST_BATCH_DRAIN_CHUNKS = 50


def stream_openrouter(
    api_key: str,
    model: str,
    system: str | list,
    messages: list,
    tool_schemas: list,
    config: dict,
    base_url: str = OPENROUTER_BASE_URL,
    session_factory=None,
    send_reasoning: bool = True,
    reasoning_effort: str | None = None,
    provider_label: str = "OpenRouter",
    stable_blocks: int = 0,
    native: bool | None = None,
) -> Generator:
    """Stream from an OpenAI-compatible endpoint (OpenRouter by default, or the
    internal LLM gateway preprod via base_url/session_factory overrides). Tool calls are
    parsed from XML in the text stream (see xml_tool_protocol/) — same protocol
    as the Anthropic backend, so the rest of the agent loop is provider-agnostic.

    send_reasoning=False omits the OpenRouter-specific `reasoning` param, which
    the internal LLM gateway (Azure/OpenAI behind LiteLLM) rejects with HTTP 400.
    reasoning_effort sets the OpenAI `reasoning_effort` (e.g. "low") for GPT-5
    reasoning models. provider_label names the backend in logs/errors (the gateway
    reuses this OpenRouter streamer, so the label must not always say OpenRouter)."""
    # plus de urllib3.disable_warnings — un appel non vérifié (repli
    # BOUZECODE_TLS_INSECURE=1) doit rester visible.
    # ntlm_auth still calls the pre-48.0 cryptography ARC4 path during the NTLM
    # proxy handshake; the warning is cosmetic and pollutes the spinner output.
    import warnings
    warnings.filterwarnings("ignore", message=".*ARC4 has been moved.*")

    # Reasoning is gated on thinking_mode, mirroring the Anthropic backend, and
    # streamed as visible ThinkingChunks (billed by OpenRouter as output tokens).
    # The caller already resolved the provider from the full id ("openrouter/anthropic/…");
    # re-resolving the stripped id would mistake it for a direct Anthropic model (XML tools).
    if native is None:
        native = model_uses_native_tools(model, config)
    payload = {
        "model": model,
        "max_tokens": config.get("max_tokens", 8192),
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    if native:
        payload["messages"] = _messages_natifs(messages, system, model, stable_blocks)
        payload["tools"] = tool_schemas_to_openai(tool_schemas)
        # Default "auto"; a focused recovery call forces e.g.
        # {"type": "function", "function": {"name": "Methodology"}}.
        payload["tool_choice"] = resolve_tool_choice(model, config)
    else:
        payload["messages"] = _messages_to_openai(messages, _system_content(system, model), model)
        # No API-level stop marker: see the Anthropic backend. The batch end is
        # detected client-side by XmlToolStreamParser.batch_closed (top level
        # only) and we hang up, so a literal mention of the protocol syntax
        # inside a param no longer truncates the turn.
    if send_reasoning and config.get("native_reasoning", False):
        payload["reasoning"] = {"enabled": True}
    if reasoning_effort:
        payload["reasoning_effort"] = reasoning_effort
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    # En-têtes X-Demo-* : seulement vers le proxy LLM du portail (jamais OpenRouter).
    from bouzecode.backend.agent.providers.llm_proxy import proxy_headers

    headers.update(proxy_headers(base_url, config))
    verify = requests_verify(provider_label)

    # Resolve _build_session as a module global at call time (not as a default
    # arg) so tests that monkeypatch openrouter_stream._build_session take effect.
    session = (session_factory or _build_session)()
    # Fournisseur épinglé (réglage `openrouter_provider`) : OpenRouter seulement, pas le gateway.
    route_config = openrouter_provider.routage(config, base_url == OPENROUTER_BASE_URL)
    servis: list = []
    started = False
    attempt = 0
    #  Tentatives facturées puis écartées (refus, coupure) : comptées dans le tour ET
    #  journalisées une à une dans turns.jsonl (cf. tentative_ecartee).
    ecartees: list[dict] = []
    stream_timeout_backoffs = list(_STREAM_TIMEOUT_BACKOFFS_S)
    stream_error_backoffs = list(_STREAM_ERROR_BACKOFFS_S)
    # Chien de garde de PROGRÈS (stream_progress) : le délai de lecture seul se réarme sur
    # chaque keep-alive. Le silence TOTAL du socket est borné par le même délai.
    first_progress_s, progress_s = progress_timeouts(config)
    read_timeout_s = max(first_progress_s, progress_s)
    while True:
        resp = openrouter_provider.poster(lambda p: session.post(
            f"{base_url}/chat/completions",
            headers=headers, json=p, verify=verify, stream=True, timeout=(10, read_timeout_s),
        ), payload, route_config, model, _sleep,
            functools.partial(post_with_retry, label=provider_label))
        # requests defaults text/* (incl. text/event-stream) to ISO-8859-1 when the
        # response carries no charset, which mojibakes UTF-8 (é -> Ã©). Force UTF-8.
        resp.encoding = "utf-8"

        xml_parser = XmlToolStreamParser()
        tool_calls: list = []
        tool_buf: dict = {}
        text = ""
        from ..types import UsageSnapshot
        in_tokens = out_tokens = cache_read_tokens = cache_write_tokens = 0
        stop_reason = None
        saw_reasoning = False
        # Refus EXPLICITE du modèle, remonté tel quel sur l'AssistantTurn : il
        # discrimine un refus DÉTERMINISTE (relancer la même requête redonnera le
        # même vide) d'un glitch de provider, seul cas où un retry a du sens.
        refusal = None
        content_filtered = False
        batch_done = False
        post_batch_chunks = 0
        watchdog = ProgressWatchdog(first_progress_s, progress_s)

        try:
            for chunk in _iter_sse(resp, watchdog):
                if chunk_makes_progress(chunk):
                    watchdog.progress()
                servis.append(chunk.get("provider"))
                usage = chunk.get("usage")
                if usage:
                    (in_tokens, out_tokens,
                     cache_read_tokens, cache_write_tokens) = _usage_tokens(usage)
                    # Surface usage NOW: a stream that dies before its final
                    # AssistantTurn must still report what it consumed.
                    yield UsageSnapshot(in_tokens, out_tokens,
                                        cache_read_tokens, cache_write_tokens)
                error_message = stream_error_message(chunk)
                if error_message and stream_error_backoffs:
                    raise UpstreamStreamError(error_message)
                if batch_done:
                    # The batch is closed, so the turn's content is complete —
                    # but an OpenAI-compatible stream reports `usage` only in its
                    # FINAL chunk, after every `choices`. Hanging up on
                    # batch_closed dropped that chunk, so every token counter
                    # read zero. Keep draining (ignoring trailing text) until the
                    # usage lands, bounded by _POST_BATCH_DRAIN_CHUNKS.
                    if in_tokens or out_tokens:
                        break
                    post_batch_chunks += 1
                    if post_batch_chunks > _POST_BATCH_DRAIN_CHUNKS:
                        break
                    continue
                choices = chunk.get("choices") or []
                if not choices:
                    continue
                if not started:
                    started = True
                    yield StreamStarted()
                delta = choices[0].get("delta") or {}
                if delta.get("reasoning"):
                    saw_reasoning = True
                    yield ThinkingChunk(delta["reasoning"])
                # OpenAI-compatible refusal: the model declines in a dedicated
                # field instead of `content`, so the turn looks empty on the wire.
                if delta.get("refusal"):
                    refusal = (refusal or "") + str(delta["refusal"])
                if native and delta.get("tool_calls"):
                    accumulate_tool_call_deltas(delta["tool_calls"], tool_buf)
                content = delta.get("content")
                if content:
                    if native:
                        text += content
                        yield TextChunk(content)
                    else:
                        items = xml_parser.feed(content)
                        # Transcript = raw text minus an orphan wrapper tail (see parser.feed).
                        text += xml_parser.history_delta
                        for item in items:
                            if isinstance(item, str):
                                yield TextChunk(item)
                            else:
                                yield ToolCallParsed(item["name"], item["input"], item["id"])
                                tool_calls.append(item)
                        if xml_parser.batch_closed:
                            # Batch closed at top level: stop consuming content
                            # instead of asking the API to cut on a marker, which
                            # also fired on a literal mention of the syntax inside
                            # a param. We stay on the stream (see the drain above)
                            # only to collect the trailing usage chunk.
                            batch_done = True
                if choices[0].get("finish_reason"):
                    stop_reason = choices[0]["finish_reason"]
                # content_filter = the endpoint (or the model) refused. Mark it as a
                # refusal so the loop can close with a cause instead of bouncing on a
                # glitch path (never replayed as-is: see below).
                if "content_filter" in (str(choices[0].get("finish_reason") or ""),
                                        str(choices[0].get("native_finish_reason") or "")):
                    refusal = refusal or True
                    content_filtered = True
        except transport_errors() as exc:
            # Replaying is only safe while nothing has reached the UI: once text
            # or a tool call went out, a second pass would duplicate it.
            produced = bool(text or tool_buf or tool_calls or saw_reasoning)
            if produced:
                #  Coupure APRÈS production (session 9d81964e : ChunkedEncodingError au 69e
                #  tour) : rejouée comme une erreur de flux en vol — StreamRestart fait jeter
                #  la tentative avortée au consommateur —, dans le même budget.
                if not stream_error_backoffs:
                    raise
                delay = stream_error_backoffs.pop(0)
                logger.warning("%s connection dropped mid-stream after output (%s: %s); "
                               "replaying the request in %.0fs",
                               provider_label, type(exc).__name__, exc, delay)
                ecartees.append(tentative_ecartee("coupure_en_vol", in_tokens, out_tokens,
                                                   cache_read_tokens, cache_write_tokens))
                _sleep(delay)
                if started:
                    started = False
                    yield StreamRestart()
                continue
            if not stream_timeout_backoffs:
                raise
            delay = stream_timeout_backoffs.pop(0)
            logger.warning(
                "%s connection dropped mid-stream (%s: %s); nothing streamed yet, "
                "replaying the request in %.0fs",
                provider_label, type(exc).__name__, exc, delay,
            )
            _sleep(delay)
            continue
        except UpstreamStreamError as exc:
            # Error chunk, or StreamNoProgress from the watchdog (raised whatever the
            # budget: once it is spent, the stalled attempt fails instead of hanging).
            if isinstance(exc, StreamNoProgress):
                resp.close()  # the stalled socket is still open: free it before replaying
            if not stream_error_backoffs:
                raise
            delay = stream_error_backoffs.pop(0)
            logger.warning("%s stream failed mid-flight (%s: %s); replaying the request "
                           "in %.0fs", provider_label, type(exc).__name__, exc, delay)
            ecartees.append(tentative_ecartee("erreur_de_flux", in_tokens, out_tokens,
                                               cache_read_tokens, cache_write_tokens))
            _sleep(delay)
            if started:
                started = False
                yield StreamRestart()
            continue
        produced = bool(text.strip() or tool_buf or tool_calls or saw_reasoning)
        # Refus content_filter : PAS de relance à l'identique — déterministe pour un contexte
        # donné (content_filter_report). Il remonte tel quel ; la boucle rejoue le tour avec
        # la note compactée, puis sur la chaîne de repli (agent/refusal_fallback.py).
        if content_filtered and not produced:
            report_content_filter_refusal(
                model=model, provider_label=provider_label, stop_reason=stop_reason,
                usage={"in": in_tokens, "out": out_tokens,
                       "cache_read": cache_read_tokens, "cache_write": cache_write_tokens})
        # text.strip(): a completion made of nothing but whitespace is just as
        # degenerate as an empty one (measured 2026-09-28: a couple of whitespace
        # tokens made `text` truthy, so this retry never armed while the agent loop
        # saw a totally empty turn and closed the run). A refusal is not replayed
        # as an empty completion (content_filter included: see above).
        if produced or refusal:
            break
        if attempt >= _EMPTY_COMPLETION_RETRIES:
            break
        attempt += 1
        logger.warning(
            "%s returned an empty completion (finish=%s); retrying %d/%d",
            provider_label, stop_reason, attempt, _EMPTY_COMPLETION_RETRIES,
        )

    if native:
        finalized = finalize_tool_calls(tool_buf)
    else:
        finalized = xml_parser.finalize()
    for tc in finalized:
        yield ToolCallParsed(tc["name"], tc["input"], tc["id"])
    tool_calls.extend(finalized)

    servi = next(filter(None, servis), "")
    openrouter_provider.noter_servi(route_config, model, servi)
    # A refusal surfaces as a normal "stop" on most endpoints (only the dedicated
    # `refusal` field carries it), which is indistinguishable from a provider
    # glitch downstream. Normalise it to content_filter so the agent loop closes
    # with a cause instead of bouncing. Never clobber a truncation reason
    # (max_tokens/length): that one drives a different recovery.
    if refusal and stop_reason in (None, "stop"):
        stop_reason = "content_filter"
    turn = AssistantTurn(text, tool_calls,
                         in_tokens + sum(t["in_tokens"] for t in ecartees),
                         out_tokens + sum(t["out_tokens"] for t in ecartees),
                         cache_read_tokens + sum(t["cache_read_tokens"] for t in ecartees),
                         cache_write_tokens + sum(t["cache_creation_tokens"] for t in ecartees),
                         stop_reason=stop_reason)
    turn.tentatives_ecartees = ecartees
    turn.provider = servi
    turn.refusal = refusal
    yield turn
