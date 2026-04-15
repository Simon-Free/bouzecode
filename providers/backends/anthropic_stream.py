# [desc] Streams responses from the Anthropic API with XML-based tool call parsing and adaptive thinking support. [/desc]
from __future__ import annotations
import os
import sys
import time
from typing import Generator

from providers.types import (
    _supports_adaptive_thinking,
    StreamStarted, TextChunk, ThinkingChunk, AssistantTurn,
)
from providers.conversion import messages_to_anthropic
from providers.backends.anthropic_helpers import (
    _create_anthropic_stream_with_retry,
    _install_sse_diagnostic_patch, _iter_stream_resilient,
    _StreamInterrupted,
)
from providers.registry import (
    _CONNECTION_RETRY_MAX_ATTEMPTS, _CONNECTION_RETRY_BASE_S,
    _CONNECTION_RETRY_MAX_DELAY_S,
)
from xml_tool_protocol import XmlToolStreamParser


def stream_anthropic(
    api_key: str,
    model: str,
    system: str,
    messages: list,
    tool_schemas: list,
    config: dict,
    *,
    base_url: str | None = None,
) -> Generator:
    """Stream from Anthropic. Tool calls are parsed from XML in the text stream
    (see xml_tool_protocol/) rather than from native tool_use SSE blocks, which
    some upstream proxies mangle."""
    import anthropic as _ant
    import httpx as _httpx
    import socket as _socket
    _install_sse_diagnostic_patch()
    _skip_ssl = os.environ.get("PYTHONHTTPSVERIFY", "1") == "0"
    _timeout = _httpx.Timeout(connect=10, read=300, write=30, pool=10)
    _keepalive_opts = [
        (_socket.SOL_SOCKET, _socket.SO_KEEPALIVE, 1),
        (_socket.IPPROTO_TCP, _socket.TCP_KEEPIDLE, 30),
        (_socket.IPPROTO_TCP, _socket.TCP_KEEPINTVL, 10),
        (_socket.IPPROTO_TCP, _socket.TCP_KEEPCNT, 3),
    ]
    _transport = _httpx.HTTPTransport(
        verify=not _skip_ssl, socket_options=_keepalive_opts,
    ) if _skip_ssl else None
    _http_client = _httpx.Client(
        timeout=_timeout, transport=_transport,
    ) if _transport else None
    client = _ant.Anthropic(
        api_key=api_key,
        base_url=base_url or None,
        http_client=_http_client,
        max_retries=3,
    )

    kwargs = {
        "model":      model,
        "max_tokens": config.get("max_tokens", 8192),
        "system":     system,
        "messages":   messages_to_anthropic(messages),
    }
    if config.get("thinking"):
        if _supports_adaptive_thinking(model):
            kwargs["thinking"] = {"type": "adaptive"}
            kwargs["output_config"] = {
                "effort": config.get("thinking_effort", "high"),
            }
        else:
            kwargs["thinking"] = {
                "type":          "enabled",
                "budget_tokens": config.get("thinking_budget", 10000),
            }

    def _warn(m):
        banner = "\r\x1b[2K\x1b[1;41;97m" + m + "\x1b[0m"
        print(banner, file=sys.stderr, flush=True)
        print(banner, flush=True)

    mid_stream_attempts = 0
    _stream_started = False
    while True:
        xml_parser = XmlToolStreamParser()
        tool_calls    = []
        text          = ""
        in_tokens     = 0
        out_tokens    = 0
        cache_read_tokens     = 0
        cache_creation_tokens = 0
        stop_reason   = None

        stream_ctx = _create_anthropic_stream_with_retry(client, kwargs)
        try:
            with stream_ctx as stream:
                for event in _iter_stream_resilient(stream, _warn):
                    etype = getattr(event, "type", None)
                    if etype == "message_start":
                        usage = event.message.usage
                        in_tokens = usage.input_tokens
                        cache_read_tokens = getattr(usage, "cache_read_input_tokens", 0) or 0
                        cache_creation_tokens = getattr(usage, "cache_creation_input_tokens", 0) or 0
                    elif etype == "content_block_start":
                        if not _stream_started:
                            _stream_started = True
                            yield StreamStarted()
                    elif etype == "content_block_delta":
                        delta = event.delta
                        dtype = getattr(delta, "type", None)
                        if dtype == "text_delta":
                            text += delta.text
                            visible, completed = xml_parser.feed(delta.text)
                            if visible:
                                yield TextChunk(visible)
                            tool_calls.extend(completed)
                        elif dtype == "thinking_delta":
                            yield ThinkingChunk(delta.thinking)
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
                        stop_reason = getattr(event.delta, "stop_reason", None) or stop_reason
            break
        except _StreamInterrupted as exc:
            mid_stream_attempts += 1
            if mid_stream_attempts >= _CONNECTION_RETRY_MAX_ATTEMPTS:
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
                f"(attempt {mid_stream_attempts}/{_CONNECTION_RETRY_MAX_ATTEMPTS}); "
                f"partial text discarded, server will re-generate from scratch."
            )
            time.sleep(delay)

    tool_calls.extend(xml_parser.finalize())

    if stop_reason == "max_tokens":
        _warn(
            f"[stream] \u26a0  Anthropic truncated the response: stop_reason=max_tokens "
            f"(out_tokens={out_tokens}, cap={kwargs['max_tokens']}). "
            f"Raise config['max_tokens'] to let it finish."
        )

    yield AssistantTurn(text, tool_calls, in_tokens, out_tokens,
                        cache_read_tokens, cache_creation_tokens)
