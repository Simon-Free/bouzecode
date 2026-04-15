# [desc] Package init exposing XML tool-call protocol parser, serializer, and doc builder. [/desc]
"""XML-text tool-call protocol — bypasses native Anthropic tool_use SSE blocks
that get mangled by some upstream proxies. The LLM emits <tool_use> blocks in
text; the client parses them locally."""
from __future__ import annotations

from xml_tool_protocol.parser import XmlToolStreamParser
from xml_tool_protocol.serializer import serialize_tool_call, serialize_tool_result
from xml_tool_protocol.docs import build_tool_docs

__all__ = [
    "XmlToolStreamParser",
    "serialize_tool_call",
    "serialize_tool_result",
    "build_tool_docs",
]
