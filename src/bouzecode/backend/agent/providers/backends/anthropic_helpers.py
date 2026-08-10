# [desc] Retry logic, SSE diagnostics, and stream helpers for the Anthropic API provider. [/desc]
from __future__ import annotations
import json
import os
import sys
import time
from typing import Callable, Generator

from ..registry import (
    _RATE_LIMIT_RETRY_INTERVAL_S, _RATE_LIMIT_RETRY_BUDGET_S,
    _CONNECTION_RETRY_MAX_ATTEMPTS, _CONNECTION_RETRY_BASE_S,
    _CONNECTION_RETRY_MAX_DELAY_S,
)

# A corporate LLM gateway fronting Bedrock sometimes wraps a transient upstream 5xx
# as a 400 with a LiteLLM body. These lowercase substrings mark such a transient
# outage (retry it like a 5xx). A 400 matching NONE of them is a real client error.
_TRANSIENT_GATEWAY_MARKERS = (
    "bedrockexception",
    "no fallback model group",
    "litellm",
)


def _create_anthropic_stream_with_retry(
    client,
    kwargs: dict,
    *,
    interval_s: float = _RATE_LIMIT_RETRY_INTERVAL_S,
    budget_s: float = _RATE_LIMIT_RETRY_BUDGET_S,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], float] = time.monotonic,
    warn: Callable[[str], None] = lambda m: print(m, file=sys.stderr, flush=True),
):
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
        except _ant.RateLimitError:
            rate_limit_attempts += 1
            elapsed = now() - start
            if elapsed >= budget_s:
                raise
            warn(
                f"\x1b[33m\u27f3 Rate limited by Anthropic, retrying in {interval_s:.0f}s... "
                f"(attempt {rate_limit_attempts}, elapsed {elapsed:.0f}s/{budget_s:.0f}s)\x1b[0m"
            )
            sleep(interval_s)
        except _ant.APIConnectionError as exc:
            connection_attempts += 1
            if connection_attempts >= _CONNECTION_RETRY_MAX_ATTEMPTS:
                raise
            delay = min(
                _CONNECTION_RETRY_BASE_S * (2 ** (connection_attempts - 1)),
                _CONNECTION_RETRY_MAX_DELAY_S,
            )
            warn(
                f"\x1b[33m\u27f3 Connection error ({type(exc).__name__}: {exc}), "
                f"retrying in {delay:.0f}s... "
                f"(attempt {connection_attempts}/{_CONNECTION_RETRY_MAX_ATTEMPTS})\x1b[0m"
            )
            sleep(delay)
        except _ant.InternalServerError as exc:
            server_error_attempts += 1
            if server_error_attempts >= _CONNECTION_RETRY_MAX_ATTEMPTS:
                raise
            delay = min(
                _CONNECTION_RETRY_BASE_S * (2 ** (server_error_attempts - 1)),
                _CONNECTION_RETRY_MAX_DELAY_S,
            )
            warn(
                f"\x1b[33m\u27f3 Server error {exc.status_code} ({exc}), "
                f"retrying in {delay:.0f}s... "
                f"(attempt {server_error_attempts}/{_CONNECTION_RETRY_MAX_ATTEMPTS})\x1b[0m"
            )
            sleep(delay)
        except _ant.BadRequestError as exc:
            # A genuine 400 (malformed request, context too long, unknown tool,
            # invalid image) is FATAL and must propagate. BUT a corporate LLM
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
                f"\x1b[33m\u27f3 Transient gateway 400 ({exc}), "
                f"retrying in {delay:.0f}s... "
                f"(attempt {gateway_error_attempts}/{_CONNECTION_RETRY_MAX_ATTEMPTS})\x1b[0m"
            )
            sleep(delay)
        except _ant.AuthenticationError as exc:
            msg = str(exc)
            if "not allowed to access model" in msg or "key_model_access_denied" in msg:
                warn(f"\x1b[31m✗ Model access denied: {msg}\x1b[0m")
                raise
            auth_error_attempts += 1
            # Some gateways return a transient 401 ("Client is not connected
            # to the query engine, you must call connect()...") on cold sessions;
            # the session warms on the very next call, so retry near-immediately
            # instead of backing off 2s/4s. Allow more attempts for this case.
            transient_warmup = "not connected" in msg or "connect()" in msg
            max_attempts = 6 if transient_warmup else 3
            if auth_error_attempts >= max_attempts:
                raise
            delay = 0.25 if transient_warmup else 2.0 * (2 ** (auth_error_attempts - 1))
            warn(
                f"\x1b[33m\u27f3 Auth error 401: {msg}\n"
                f"  Retrying in {delay:.2f}s... "
                f"(attempt {auth_error_attempts}/{max_attempts})\x1b[0m"
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
# this many seconds AFTER the first one. 15s is fine on a fast LAN to a gateway
# but too aggressive over a slower cloud→gateway path under load (long gaps
# between tokens on large contexts get falsely flagged as stalls, triggering a
# costly full-request retry storm). Configurable via env; default raised to 60s.
_INTER_CHUNK_TIMEOUT_S = int(os.environ.get("BOUZECODE_INTER_CHUNK_TIMEOUT_S", "60"))


def _iter_stream_resilient(stream, warn: Callable[[str], None]) -> Generator:
    """Iterate over SSE stream events with a 15s inter-chunk stall detector.

    A background thread reads from the stream (blocking) and feeds a queue.
    The consumer pulls from the queue with a timeout — if no event arrives
    within _INTER_CHUNK_TIMEOUT_S after the first event, the connection is
    considered stalled and _StreamInterrupted is raised.
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
            timeout = _INTER_CHUNK_TIMEOUT_S if got_first else None
            try:
                tag, value = q.get(timeout=timeout)
            except _queue.Empty:
                warn(
                    f"[stream] no data received for {_INTER_CHUNK_TIMEOUT_S}s, "
                    f"killing stalled connection"
                )
                raise _StreamInterrupted(
                    f"inter-chunk stall >{_INTER_CHUNK_TIMEOUT_S}s"
                )

            if tag == "done":
                return
            elif tag == "error":
                e = value
                if isinstance(e, (StopIteration, GeneratorExit)):
                    return
                elif isinstance(e, (json.JSONDecodeError, UnicodeDecodeError)):
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
