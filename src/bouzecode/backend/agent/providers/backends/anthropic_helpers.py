# [desc] Retry logic, SSE diagnostics, and stream helpers for the Anthropic API provider. [/desc]
from __future__ import annotations
import json
import logging
import os
import sys
import time
from typing import Callable, Generator

from ..registry import (
    _RATE_LIMIT_RETRY_INTERVAL_S, _RATE_LIMIT_RETRY_BUDGET_S,
    _CONNECTION_RETRY_MAX_ATTEMPTS, _CONNECTION_RETRY_BASE_S,
    _CONNECTION_RETRY_MAX_DELAY_S,
)
from ....core.tls import certificate_error_hint

logger = logging.getLogger(__name__)

# The corporate Bedrock gateway sometimes wraps a transient upstream 5xx as a 400 with a
# LiteLLM body. These lowercase substrings mark such a transient outage (retry it like
# a 5xx). A 400 whose body matches NONE of these is a genuine client error → fatal.
_TRANSIENT_GATEWAY_MARKERS = (
    "bedrockexception",
    "no fallback model group",
    "litellm",
)


_RATE_LIMIT_RETRY_MAX_DELAY_S = 30.0

# Types d'erreur d'un événement SSE `error` reçu EN PLEIN FLUX, après un create réussi.
# Le SDK le lève en APIStatusError portant le statut de la réponse, donc 200 : aucune
# relance du create ne le voit, et il tuait la session (api_error). Ce sont des pannes
# passagères du fournisseur : on rejoue le flux comme une coupure en vol.
_TRANSIENT_STREAM_ERROR_TYPES = ("overloaded_error", "rate_limit_error", "api_error")


def _is_transient_stream_error(exc) -> bool:
    """Erreur SSE `error` en plein flux (statut HTTP 200) d'un type passager."""
    import anthropic as _ant
    return (isinstance(exc, _ant.APIStatusError) and exc.status_code < 400
            and getattr(exc, "type", None) in _TRANSIENT_STREAM_ERROR_TYPES)


def _retry_after_seconds(exc) -> float | None:
    """Return the server's Retry-After delay (seconds) if present and numeric."""
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    if not headers:
        return None
    try:
        value = headers.get("retry-after") or headers.get("Retry-After")
    except Exception:
        return None
    try:
        return max(0.0, float(value)) if value is not None else None
    except (TypeError, ValueError):
        return None


def _create_anthropic_stream_with_retry(
    client,
    kwargs: dict,
    *,
    interval_s: float = _RATE_LIMIT_RETRY_INTERVAL_S,
    budget_s: float = _RATE_LIMIT_RETRY_BUDGET_S,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], float] = time.monotonic,
    warn: Callable[[str], None] = logger.warning,
):
    """Ouvre le flux, en relançant les erreurs passagères du `create`.

    Chaque relance est journalisée par `warn` : le journal du process par défaut
    (~/.bouzecode/logs), jamais stderr, qui s'imprimait au milieu du chat. Le client est
    construit avec max_retries=0 : cette boucle voit donc CHAQUE 429, 529 et 5xx."""
    import anthropic as _ant
    start = now()
    rate_limit_attempts = 0
    connection_attempts = 0
    server_error_attempts = 0
    auth_error_attempts = 0
    gateway_error_attempts = 0
    while True:
        try:
            return client.messages.create(**kwargs, stream=True, cache_control=None)
        except _ant.RateLimitError as exc:
            rate_limit_attempts += 1
            elapsed = now() - start
            remaining = budget_s - elapsed
            if remaining <= 0:
                raise
            # Progressive backoff: interval, 2x, 4x... capped, unless the
            # server tells us how long to wait (Retry-After).
            delay = _retry_after_seconds(exc)
            if delay is None:
                delay = min(
                    interval_s * (2 ** (rate_limit_attempts - 1)),
                    _RATE_LIMIT_RETRY_MAX_DELAY_S,
                )
            delay = min(delay, remaining)
            warn(
                f"\u27f3 Rate limited by Anthropic, retrying in {delay:.0f}s... "
                f"(attempt {rate_limit_attempts}, elapsed {elapsed:.0f}s/{budget_s:.0f}s)"
            )
            sleep(delay)
        except _ant.APIConnectionError as exc:
            # Un certificat refusé ne se répare pas en réessayant : on
            # le dit clairement et on rend l'exception d'origine.
            hint = certificate_error_hint(exc)
            if hint:
                warn(hint)
                raise
            connection_attempts += 1
            if connection_attempts >= _CONNECTION_RETRY_MAX_ATTEMPTS:
                raise
            delay = min(
                _CONNECTION_RETRY_BASE_S * (2 ** (connection_attempts - 1)),
                _CONNECTION_RETRY_MAX_DELAY_S,
            )
            warn(
                f"\u27f3 Connection error ({type(exc).__name__}: {exc}), "
                f"retrying in {delay:.0f}s... "
                f"(attempt {connection_attempts}/{_CONNECTION_RETRY_MAX_ATTEMPTS})"
            )
            sleep(delay)
        except (_ant.InternalServerError, _ant.ConflictError,
                getattr(_ant, "OverloadedError", _ant.InternalServerError)) as exc:
            # 529 : OverloadedError hérite d'APIStatusError, PAS d'InternalServerError.
            # 409 : relancé par le SDK tant qu'il avait max_retries > 0, on le reprend ici.
            server_error_attempts += 1
            if server_error_attempts >= _CONNECTION_RETRY_MAX_ATTEMPTS:
                raise
            delay = _retry_after_seconds(exc)
            if delay is None:
                delay = _CONNECTION_RETRY_BASE_S * (2 ** (server_error_attempts - 1))
            delay = min(delay, _CONNECTION_RETRY_MAX_DELAY_S)
            warn(
                f"\u27f3 Server error {exc.status_code} ({exc}), "
                f"retrying in {delay:.0f}s... "
                f"(attempt {server_error_attempts}/{_CONNECTION_RETRY_MAX_ATTEMPTS})"
            )
            sleep(delay)
        except _ant.BadRequestError as exc:
            # A genuine 400 (malformed request, context too long, unknown tool,
            # invalid image) is FATAL and must propagate. BUT the corporate Bedrock
            # gateway occasionally wraps a transient 5xx as a 400 with a LiteLLM
            # body ("BedrockException", "No fallback model group", empty {}). That
            # is a transient outage, not a client bug — retry it like a 5xx.
            msg = str(exc).lower()
            if not any(marker in msg for marker in _TRANSIENT_GATEWAY_MARKERS):
                raise  # real client-side 400 — fatal
            gateway_error_attempts += 1
            if gateway_error_attempts >= _CONNECTION_RETRY_MAX_ATTEMPTS:
                raise
            delay = min(
                _CONNECTION_RETRY_BASE_S * (2 ** (gateway_error_attempts - 1)),
                _CONNECTION_RETRY_MAX_DELAY_S,
            )
            warn(
                f"\u27f3 Transient gateway 400 ({exc}), "
                f"retrying in {delay:.0f}s... "
                f"(attempt {gateway_error_attempts}/{_CONNECTION_RETRY_MAX_ATTEMPTS})"
            )
            sleep(delay)
        except _ant.AuthenticationError as exc:
            msg = str(exc)
            if "not allowed to access model" in msg or "key_model_access_denied" in msg:
                warn(f"✗ Model access denied: {msg}")
                raise
            auth_error_attempts += 1
            # The internal LLM gateway returns a transient 401 ("Client is not connected
            # to the query engine, you must call connect()...") on cold sessions;
            # the session warms on the very next call, so retry near-immediately
            # instead of backing off 2s/4s. Allow more attempts for this case.
            transient_warmup = "not connected" in msg or "connect()" in msg
            max_attempts = 6 if transient_warmup else 3
            if auth_error_attempts >= max_attempts:
                raise
            delay = 0.25 if transient_warmup else 2.0 * (2 ** (auth_error_attempts - 1))
            warn(
                f"\u27f3 Auth error 401: {msg}\n"
                f"  Retrying in {delay:.2f}s... "
                f"(attempt {auth_error_attempts}/{max_attempts})"
            )
            sleep(delay)


_SSE_PATCH_INSTALLED = False


def _install_sse_diagnostic_patch() -> None:
    global _SSE_PATCH_INSTALLED
    if _SSE_PATCH_INSTALLED:
        return
    from anthropic import _streaming as _ant_streaming
    _orig_json = _ant_streaming.ServerSentEvent.json

    def _safe_json(self):
        try:
            return _orig_json(self)
        except json.JSONDecodeError as e:
            preview = (self.data or "")[:200]
            print(
                f"\r\x1b[2K[sse-diag] json decode failed on event={self.event!r} "
                f"id={self.id!r} data_len={len(self.data or '')} "
                f"preview={preview!r} err={e}",
                file=sys.stderr, flush=True,
            )
            raise

    _ant_streaming.ServerSentEvent.json = _safe_json
    _SSE_PATCH_INSTALLED = True


class _StreamInterrupted(Exception):
    """Raised when the stream dropped mid-flight due to a network error.
    The caller is expected to discard partial state and retry the full request."""


# Inter-chunk stall detector: kill the stream if no SSE event arrives within
# this many seconds AFTER the first one. 15s is fine on a fast LAN to the gateway
# but too aggressive over the slower Azure→gateway path under load (long gaps
# between tokens on large contexts get falsely flagged as stalls, triggering a
# costly full-request retry storm). Configurable via env; default raised to 60s.
# 2026-10-12 : ramene a 15s par decision utilisateur. Thinking, texte et
# input_json arrivent en continu une fois le flux lance : attendre 60s un flux
# mort coutait trop cher en temps. Si les rafales de relances reviennent sur la
# route Azure->gateway, remonter via BOUZECODE_INTER_CHUNK_TIMEOUT_S.
_INTER_CHUNK_TIMEOUT_S = int(os.environ.get("BOUZECODE_INTER_CHUNK_TIMEOUT_S", "15"))

# Deadline distincte pour le PREMIER evenement du flux. Elle est plus genereuse
# que _INTER_CHUNK_TIMEOUT_S parce que le premier octet peut tarder legitimement
# (file d'attente du fournisseur, ingestion d'un prompt tres long), alors qu'une
# fois le flux demarre un silence de 60s signifie une connexion morte. Mais elle
# doit EXISTER : sans elle, un flux qui ne delivre jamais rien fige l'agent
# indefiniment, sans erreur ni trace (vecu le 2026-08-25, 15 min de blocage).
# 2026-10-12 : 180s -> 60s, suffisant pour ingerer nos prompts (rarement >100k
# tokens) ; au-dela, relancer vaut mieux qu'attendre.
_FIRST_EVENT_TIMEOUT_S = int(
    os.environ.get("BOUZECODE_FIRST_EVENT_TIMEOUT_S", "60")
)

# Pourquoi cette route n'a PAS besoin du chien de garde de progres de la route
# chat/completions (stream_progress.py, examine le 2026-10-05) : les deux deadlines
# ci-dessus se rearment sur un element de la file, donc sur un evenement que le SDK a
# YIELDE. Or `anthropic._streaming.Stream.__stream__` avale les `event: ping`
# (`continue`) et ignore les commentaires SSE : un socket tenu en vie par des pings ne
# rearme rien et la deadline tombe. Seuls message_start / content_block_* /
# message_delta / message_stop passent ; une rafale indefinie de deltas VIDES reste
# theorique (jamais observee). Le filet consommateur de loop_turn (300 s) couvre le reste.


def _iter_stream_resilient(
    stream,
    warn: Callable[[str], None],
    *,
    inter_chunk_timeout_s: float = _INTER_CHUNK_TIMEOUT_S,
) -> Generator:
    """Iterate over SSE stream events with a stall detector on every wait.

    A background thread reads from the stream (blocking) and feeds a queue.
    The consumer pulls from the queue with a FINITE timeout in both phases:
    _FIRST_EVENT_TIMEOUT_S while waiting for the very first event, then
    `inter_chunk_timeout_s` (default _INTER_CHUNK_TIMEOUT_S) for each
    subsequent one. Either deadline expiring means the connection is stalled
    and _StreamInterrupted is raised (same exception in both cases, so the
    upstream retry logic applies unchanged).

    `inter_chunk_timeout_s` is only meant to be overridden by tests, so they
    can exercise the stall path without waiting a full production deadline.
    """
    import httpx as _httpx
    import anthropic as _ant
    import threading
    import queue as _queue

    it = iter(stream)
    q: _queue.Queue = _queue.Queue(maxsize=128)

    def _producer():
        try:
            for item in it:
                q.put(("event", item))
            q.put(("done", None))
        except BaseException as e:
            q.put(("error", e))

    thread = threading.Thread(target=_producer, daemon=True)
    thread.start()

    got_first = False
    try:
        while True:
            timeout = (
                inter_chunk_timeout_s if got_first else _FIRST_EVENT_TIMEOUT_S
            )
            try:
                tag, value = q.get(timeout=timeout)
            except _queue.Empty:
                if not got_first:
                    warn(
                        f"[stream] no first event in "
                        f"{_FIRST_EVENT_TIMEOUT_S}s, "
                        f"killing stalled connection"
                    )
                    raise _StreamInterrupted(
                        f"no first event >{_FIRST_EVENT_TIMEOUT_S}s"
                    )
                warn(
                    f"[stream] no data received for {inter_chunk_timeout_s}s, "
                    f"killing stalled connection"
                )
                raise _StreamInterrupted(
                    f"inter-chunk stall >{inter_chunk_timeout_s}s"
                )

            if tag == "done":
                return
            elif tag == "error":
                e = value
                if isinstance(e, (StopIteration, GeneratorExit)):
                    return
                elif isinstance(e, (json.JSONDecodeError, UnicodeDecodeError)):
                    if not got_first:
                        # Nothing usable arrived: there is no partial response to keep,
                        # so this is a failed request to retry, not an empty reply.
                        warn(f"[stream] malformed first SSE event ({type(e).__name__}); retrying")
                        raise _StreamInterrupted(f"malformed first SSE event: {e}") from e
                    warn(
                        f"[stream] upstream sent a malformed SSE event "
                        f"({type(e).__name__}: {e}); terminating stream early, "
                        f"partial response will be kept."
                    )
                    return
                elif isinstance(e, (_httpx.RemoteProtocolError, _httpx.ReadError,
                                    _httpx.ReadTimeout, _ant.APIConnectionError)):
                    warn(
                        f"[stream] upstream closed the connection mid-stream "
                        f"({type(e).__name__}: {e})"
                    )
                    raise _StreamInterrupted(str(e)) from e
                elif _is_transient_stream_error(e):
                    warn(f"[stream] upstream sent an SSE error mid-stream ({e.type}: {e})")
                    raise _StreamInterrupted(f"SSE {e.type}") from e
                else:
                    raise e
            else:
                got_first = True
                yield value
    finally:
        thread.join(timeout=2)


_KEY_TO_TOOL: list[tuple[set[str], str]] = [
    ({"command"},                          "Bash"),
    ({"file_path", "content"},             "Write"),
    ({"file_path", "old_string"},          "Edit"),
    ({"notebook_path", "new_source"},      "NotebookEdit"),
    ({"file_path", "offset"},              "Read"),
    ({"file_path"},                        "Read"),
    ({"pattern", "path"},                  "Grep"),
    ({"pattern"},                          "Glob"),
    ({"url"},                              "WebFetch"),
    ({"query"},                            "WebSearch"),
    ({"prompt"},                           "Agent"),
    ({"task_id"},                          "CheckAgentResult"),
    ({"to", "message"},                    "SendMessage"),
    ({"question"},                         "AskUserQuestion"),
    ({"seconds"},                          "SleepTimer"),
    ({"subject", "description"},           "TaskCreate"),
    ({"name", "type", "description", "content"}, "MemorySave"),
]


def _guess_tool_name(parsed_input: dict) -> str:
    keys = set(parsed_input.keys()) - {"depends_on", "tool_call_alias"}
    for required_keys, name in sorted(_KEY_TO_TOOL, key=lambda x: -len(x[0])):
        if required_keys <= keys:
            return name
    return "_UnknownRecoveredTool"
