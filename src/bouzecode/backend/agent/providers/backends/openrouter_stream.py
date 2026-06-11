# [desc] Streams from OpenRouter via requests, through the SNCF NTLM proxy, with XML tool parsing. [/desc]
from __future__ import annotations
import logging
import os
from typing import Generator

from ..types import (
    StreamStarted, TextChunk, ThinkingChunk, ToolCallParsed, AssistantTurn,
)
from ..conversion import messages_to_anthropic
from ..registry import OPENROUTER_BASE_URL, model_uses_native_tools
from ....xml_tool_protocol import XmlToolStreamParser
from .openrouter_native import (
    tool_schemas_to_openai, messages_to_openai_native,
    accumulate_tool_call_deltas, finalize_tool_calls,
)
from .openrouter_retry import post_with_retry
# _build_session stays a module attribute: tests monkeypatch it at this path.
from .openrouter_transport import build_session as _build_session, iter_sse as _iter_sse

logger = logging.getLogger(__name__)

# Some upstream providers occasionally return a degenerate completion: a single
# chunk with empty content, no reasoning, no tool_calls, finish_reason "stop"
# (observed on deepseek-v4-pro via GMICloud, 2026-06-10). Nothing substantive
# has been yielded at that point, so re-issuing the request is invisible to the
# conversation.
_EMPTY_COMPLETION_RETRIES = 2


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


def _messages_to_openai(messages: list, system: str) -> list:
    """Reuse the XML tool serialization, then flatten to OpenAI string content."""
    converted = messages_to_anthropic(messages, cache_last=False)
    oai = [{"role": "system", "content": system}]
    for m in converted:
        oai.append({"role": m["role"], "content": _content_to_text(m["content"])})
    return oai


def stream_openrouter(
    api_key: str,
    model: str,
    system: str | list,
    messages: list,
    tool_schemas: list,
    config: dict,
) -> Generator:
    """Stream from OpenRouter. Tool calls are parsed from XML in the text stream
    (see xml_tool_protocol/) — same protocol as the Anthropic backend, so the
    rest of the agent loop is provider-agnostic."""
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    # ntlm_auth still calls the pre-48.0 cryptography ARC4 path during the NTLM
    # proxy handshake; the warning is cosmetic and pollutes the spinner output.
    import warnings
    warnings.filterwarnings("ignore", message=".*ARC4 has been moved.*")

    # Reasoning is gated on thinking_mode, mirroring the Anthropic backend, and
    # streamed as visible ThinkingChunks (billed by OpenRouter as output tokens).
    native = model_uses_native_tools(model, config)
    payload = {
        "model": model,
        "max_tokens": config.get("max_tokens", 8192),
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    if native:
        payload["messages"] = messages_to_openai_native(messages, _system_text(system))
        payload["tools"] = tool_schemas_to_openai(tool_schemas)
        # Default "auto"; a focused recovery call forces e.g.
        # {"type": "function", "function": {"name": "Methodology"}}.
        payload["tool_choice"] = config.get("_tool_choice") or "auto"
    else:
        payload["messages"] = _messages_to_openai(messages, _system_text(system))
    if config.get("thinking_mode") in ("extended", "loud"):
        payload["reasoning"] = {"enabled": True}
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    verify = os.environ.get("PYTHONHTTPSVERIFY", "1") != "0"

    session = _build_session()
    started = False
    for attempt in range(_EMPTY_COMPLETION_RETRIES + 1):
        resp = post_with_retry(lambda: session.post(
            f"{OPENROUTER_BASE_URL}/chat/completions",
            headers=headers, json=payload, verify=verify, stream=True, timeout=(10, 180),
        ))
        # requests defaults text/* (incl. text/event-stream) to ISO-8859-1 when the
        # response carries no charset, which mojibakes UTF-8 (é -> Ã©). Force UTF-8.
        resp.encoding = "utf-8"

        xml_parser = XmlToolStreamParser()
        tool_calls: list = []
        tool_buf: dict = {}
        text = ""
        in_tokens = out_tokens = cache_read_tokens = 0
        stop_reason = None
        saw_reasoning = False

        for chunk in _iter_sse(resp):
            usage = chunk.get("usage")
            if usage:
                in_tokens = usage.get("prompt_tokens", 0) or 0
                out_tokens = usage.get("completion_tokens", 0) or 0
                details = usage.get("prompt_tokens_details") or {}
                cache_read_tokens = details.get("cached_tokens", 0) or 0
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
            if native and delta.get("tool_calls"):
                accumulate_tool_call_deltas(delta["tool_calls"], tool_buf)
            content = delta.get("content")
            if content:
                text += content
                if native:
                    yield TextChunk(content)
                else:
                    for item in xml_parser.feed(content):
                        if isinstance(item, str):
                            yield TextChunk(item)
                        else:
                            yield ToolCallParsed(item["name"], item["input"], item["id"])
                            tool_calls.append(item)
            if choices[0].get("finish_reason"):
                stop_reason = choices[0]["finish_reason"]
        if text or tool_buf or tool_calls or saw_reasoning:
            break
        if attempt < _EMPTY_COMPLETION_RETRIES:
            logger.warning(
                "OpenRouter returned an empty completion (finish=%s); retrying %d/%d",
                stop_reason, attempt + 1, _EMPTY_COMPLETION_RETRIES,
            )

    if native:
        finalized = finalize_tool_calls(tool_buf)
    else:
        finalized = xml_parser.finalize()
    for tc in finalized:
        yield ToolCallParsed(tc["name"], tc["input"], tc["id"])
    tool_calls.extend(finalized)

    yield AssistantTurn(text, tool_calls, in_tokens, out_tokens,
                        cache_read_tokens, 0, stop_reason=stop_reason)
