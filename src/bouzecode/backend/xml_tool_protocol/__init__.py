# [desc] Package init exposing XML tool-call protocol parser, serializer, and doc builder. [/desc]
"""XML-text tool-call protocol: the LLM emits <tool_use> blocks in text and the
client parses them locally.

HISTORICAL NOTE — the original rationale was that the internal LLM gateway proxy mangled
native Anthropic tool_use SSE blocks. That claim dated from the initial commit
(2026-04-14) and was never tested. It was re-tested on 2026-07-27 and is FALSE:
the gateway delivers canonical tool_use / input_json_delta blocks, including
several in parallel. See docs/investigations/gateway_native_tool_use_retest.md.

This protocol therefore remains as the fallback path — for providers without
native tool calling, and while BOUZECODE_ANTHROPIC_NATIVE_TOOLS defaults to off.
Native support lives in backend/agent/providers/backends/anthropic_native.py."""
from __future__ import annotations

from ..xml_tool_protocol.parser import (
    TOOL_CALLS_CLOSE, TOOL_CALLS_OPEN, TOOL_CALLS_STOP, XmlToolStreamParser,
)
from ..xml_tool_protocol.serializer import serialize_tool_call, serialize_tool_result
from ..xml_tool_protocol.docs import build_tool_docs

__all__ = [
    "TOOL_CALLS_CLOSE",
    "TOOL_CALLS_OPEN",
    "TOOL_CALLS_STOP",
    "XmlToolStreamParser",
    "serialize_tool_call",
    "serialize_tool_result",
    "build_tool_docs",
]
