# [desc] Retry logic, SSE diagnostics, and stream helpers for the Anthropic API provider. [/desc]
from __future__ import annotations
import json
import sys
import time
from typing import Callable, Generator

from providers.registry import (
    _RATE_LIMIT_RETRY_INTERVAL_S, _RATE_LIMIT_RETRY_BUDGET_S,
    _CONNECTION_RETRY_MAX_ATTEMPTS, _CONNECTION_RETRY_BASE_S,
    _CONNECTION_RETRY_MAX_DELAY_S,
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
    while True:
        try:
            return client.messages.create(**kwargs, stream=True)
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


def _iter_stream_resilient(stream, warn: Callable[[str], None]) -> Generator:
    import httpx as _httpx
    import anthropic as _ant
    it = iter(stream)
    while True:
        try:
            yield next(it)
        except StopIteration:
            return
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            warn(
                f"[stream] upstream sent a malformed SSE event "
                f"({type(e).__name__}: {e}); terminating stream early, "
                f"partial response will be kept."
            )
            return
        except (_httpx.RemoteProtocolError, _httpx.ReadError,
                _httpx.ReadTimeout, _ant.APIConnectionError) as e:
            warn(
                f"[stream] upstream closed the connection mid-stream "
                f"({type(e).__name__}: {e})"
            )
            raise _StreamInterrupted(str(e)) from e


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
