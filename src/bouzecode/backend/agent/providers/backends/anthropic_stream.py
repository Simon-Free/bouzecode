# [desc] Streams responses from the Anthropic API, parsing tool calls from native tool_use blocks or from XML. [/desc]
from __future__ import annotations
import os
import sys
import time
from typing import Generator

from ..types import (
    _supports_adaptive_thinking,
    StreamStarted, TextChunk, ThinkingChunk, ToolCallParsed, AssistantTurn,
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
    _CONNECTION_RETRY_MAX_DELAY_S,
)
from ....xml_tool_protocol import XmlToolStreamParser


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
    Both work against the official API and against a well-behaved gateway.
    """
    _install_sse_diagnostic_patch()
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
    # Gate API-level thinking: only enable when native_reasoning is explicitly
    # opted in. Default OFF — the model reasons via manual <thinking> text
    # (routed into thinking_parts by loop_turn), not the API reasoning channel.
    if _supports_adaptive_thinking(model) and not config.get("native_reasoning", False):
        kwargs["thinking"] = {"type": "disabled"}
    # Only send the 1h-TTL beta header when at least one cache_control actually
    # asks for it — corporate LLM gateways often reject the flag otherwise.
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

    mid_stream_attempts = 0
    _stream_started = False
    _had_thinking = False
    _MID_STREAM_MAX_WHEN_THINKING = 2
    while True:
        xml_parser = XmlToolStreamParser()
        tool_blocks   = NativeToolUseAccumulator()
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
                        block = getattr(event, "content_block", None)
                        if getattr(block, "type", None) == "tool_use":
                            tool_blocks.start(event.index, block.id, block.name)
                    elif etype == "content_block_delta":
                        delta = event.delta
                        dtype = getattr(delta, "type", None)
                        if dtype == "input_json_delta":
                            tool_blocks.delta(event.index, delta.partial_json)
                        elif dtype == "text_delta":
                            text += delta.text
                            if native:
                                yield TextChunk(delta.text)
                            else:
                                for item in xml_parser.feed(delta.text):
                                    if isinstance(item, str):
                                        yield TextChunk(item)
                                    else:
                                        yield ToolCallParsed(item["name"], item["input"], item["id"])
                                        tool_calls.append(item)
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
                        stop_reason = getattr(event.delta, "stop_reason", None) or stop_reason
            break
        except _StreamInterrupted as exc:
            mid_stream_attempts += 1
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

    # Blocks the stream never closed: a truncated native block stays localised to
    # its own call, where a truncated XML block used to contaminate visible text.
    _finalized = tool_blocks.finalize() if native else xml_parser.finalize()
    for _tc in _finalized:
        yield ToolCallParsed(_tc["name"], _tc["input"], _tc["id"])
    tool_calls.extend(_finalized)

    if stop_reason == "max_tokens":
        _warn(
            f"[stream] \u26a0  Anthropic truncated the response: stop_reason=max_tokens "
            f"(out_tokens={out_tokens}, cap={kwargs['max_tokens']}). "
            f"Raise config['max_tokens'] to let it finish."
        )

    yield AssistantTurn(text, tool_calls, in_tokens, out_tokens,
                        cache_read_tokens, cache_creation_tokens,
                        stop_reason=stop_reason)
