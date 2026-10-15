# [desc] Retry policy for OpenRouter requests: backoff on 429/5xx, one retry on 400 (provider rotation), backoff on network timeouts. [/desc]
from __future__ import annotations
import logging
import time

from ....core.tls import TlsVerificationError, certificate_error_hint

logger = logging.getLogger(__name__)

# 429s come from upstream provider rate limits and clear once OpenRouter rotates
# providers; a 400 has been observed from a single bad fallback provider
# (AtlasCloud "invalid request params") right after a 429 — one rotation retry
# usually lands on a healthy provider. Total worst-case wait: ~60s.
BACKOFFS_S = (2.0, 4.0, 8.0, 16.0, 30.0)

# A dropped/slow connection to the endpoint (internal LLM gateway preprod times out under
# load: "Read timed out. (read timeout=10)") used to abort the whole turn through
# the REPL catch-all. The POST has streamed nothing yet, so replaying it is safe
# and idempotent. Own budget, separate from the HTTP-status one above: ~90s.
TRANSPORT_BACKOFFS_S = (2.0, 4.0, 8.0, 16.0, 30.0, 30.0)

# Retry-After annoncé par le serveur sur un 429/5xx : respecté jusqu'à ce plafond, au-delà
# on garde l'attente progressive (un Retry-After d'une heure ne doit pas figer la session).
RETRY_AFTER_MAX_S = 60.0


def transport_errors() -> tuple:
    """The requests exceptions worth replaying: timeouts and dropped sockets.

    Imported lazily so this module stays importable without requests, and kept
    public so the SSE read loop retries on exactly the same set."""
    import requests
    return (
        requests.exceptions.Timeout,          # incl. ConnectTimeout/ReadTimeout
        requests.exceptions.ConnectionError,  # incl. ProxyError/SSLError
        requests.exceptions.ChunkedEncodingError,
    )


def _attente(resp, defaut: float, retry_after_max: float) -> float:
    """Le Retry-After du fournisseur s'il est court (≤ retry_after_max), sinon `defaut`."""
    try:
        annonce = float((getattr(resp, "headers", None) or {}).get("Retry-After", ""))
    except (TypeError, ValueError):
        return defaut
    return annonce if 0 <= annonce <= retry_after_max else defaut


def post_with_retry(post_once, sleep=time.sleep, backoffs=BACKOFFS_S,
                    transport_backoffs=TRANSPORT_BACKOFFS_S, transitoires=(),
                    retry_after_max: float = RETRY_AFTER_MAX_S, label: str = "OpenRouter"):
    """Call post_once() -> requests.Response until one is OK.

    Retries 429/5xx (and `transitoires`, e.g. 402 for a pinned provider) through
    `backoffs` and 400 once; network timeouts and dropped connections through
    `transport_backoffs`. Any other error status — or exhausted budget — raises
    with the response body in the message. Each retry is logged (process log, never
    the chat) and waits the server's Retry-After when it is ≤ `retry_after_max`.
    `label` names the endpoint in the error (the gateway reuses this transport)."""
    backoffs = list(backoffs)
    transport_backoffs = list(transport_backoffs)
    retried_400 = False
    while True:
        try:
            resp = post_once()
        except transport_errors() as exc:
            # Un certificat refusé ne se répare pas en réessayant.
            hint = certificate_error_hint(exc)
            if hint:
                raise TlsVerificationError(hint) from exc
            if not transport_backoffs:
                raise
            delay = transport_backoffs.pop(0)
            logger.warning(
                "request failed (%s: %s); retrying in %.0fs",
                type(exc).__name__, exc, delay,
            )
            sleep(delay)
            continue
        if resp.ok:
            return resp
        if resp.status_code == 400 and not retried_400:
            retried_400 = True
            sleep(2.0)
            continue
        if (resp.status_code in (429, *transitoires) or resp.status_code >= 500) and backoffs:
            delay = _attente(resp, backoffs.pop(0), retry_after_max)
            logger.warning("HTTP %d from the endpoint; retrying in %.0fs (%d retries left)",
                           resp.status_code, delay, len(backoffs))
            sleep(delay)
            continue
        raise RuntimeError(
            f"{label} request failed: HTTP {resp.status_code}\n{resp.text[:800]}"
        )


class UpstreamStreamError(Exception):
    """Chunk `error` reçu EN PLEIN FLUX, après un POST 200 (fournisseur surchargé, coupé).

    OpenRouter le signale par un champ `error` de premier niveau et `finish_reason:
    "error"` ; LiteLLM par le seul champ `error`. Ignoré, il laissait un tour tronqué
    ou vide sans aucune trace."""


def stream_error_message(chunk: dict) -> str | None:
    """Le message d'erreur d'un chunk SSE, ou None si le chunk n'en porte pas."""
    error = chunk.get("error")
    choices = chunk.get("choices") or [{}]
    if not error and choices[0].get("finish_reason") != "error":
        return None
    if isinstance(error, dict):
        return f"{error.get('code') or error.get('type') or 'error'}: {error.get('message', '')}"
    return str(error or "finish_reason=error")
