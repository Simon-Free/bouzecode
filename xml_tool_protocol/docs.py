# [desc] Generates system-prompt documentation and XML examples for available tools in the protocol. [/desc]
# [desc] Generates system-prompt documentation and XML examples for available tools in the protocol. [/desc]
"""Builds the system-prompt section that teaches the LLM the XML tool protocol."""
from __future__ import annotations

import json
from typing import Any

from xml_tool_protocol.serializer import serialize_tool_call

_FORMAT_HEADER = """\
# Tool calls — XML protocol

You invoke tools by emitting XML blocks in your text response. The opening tag
carries the tool name as an attribute and an id you choose; each parameter is
a child element whose `name` attribute identifies the argument and whose body
is the value. Generic shape:

    <tool_use name="..." id="...">...<param name="...">value</param>...</tool_use>

Rules:
- The `id` attribute is a short identifier you choose (e.g. r1, w2). Other tools in the same turn can reference it via a `tool_call_alias` param.
- Wrap a parameter value in CDATA when it contains `<`, `>` or `&`. To embed `]]>` literally inside CDATA, use the canonical XML escape `]]]]>` followed by `<![CDATA[>`.
- Emit multiple tool blocks in the same response to run several tools in parallel — they will be dispatched concurrently when safe.
- Anything outside a tool block is rendered to the user as plain text.
- This XML is an internal transport — the user never sees it. Never quote or echo `<tool_use>`, `<param>` or any of this markup in your prose (plans, explanations, summaries). Describe tool calls in natural language: say "I will read parser.py and edit feed()", not "I will emit a `<tool_use name=\"Read\">` block". Showing the markup in prose also confuses the stream parser and corrupts subsequent tool calls.

Available tools (each section ends with a parsable example):
"""


def _example_for(schema: dict) -> str:
    properties = schema.get("input_schema", {}).get("properties", {}) or {}
    required = schema.get("input_schema", {}).get("required", []) or []
    example_input: dict[str, Any] = {}
    for prop in required or list(properties.keys())[:2]:
        spec = properties.get(prop, {})
        example_input[prop] = _example_value(prop, spec)
    return serialize_tool_call({
        "id": "x1",
        "name": schema["name"],
        "input": example_input,
    })


def _example_value(name: str, spec: dict) -> Any:
    typ = spec.get("type", "string")
    if typ == "integer":
        return 1
    if typ == "number":
        return 1.0
    if typ == "boolean":
        return True
    if typ == "array":
        return ["item"]
    if typ == "object":
        return {"key": "value"}
    return f"<{name}>"


def _format_param(prop_name: str, spec: dict, required: list[str]) -> str:
    typ = spec.get("type", "string")
    desc = spec.get("description", "").strip()
    req = "required" if prop_name in required else "optional"
    suffix = f" — {desc}" if desc else ""
    return f"  - {prop_name} ({typ}, {req}){suffix}"


def _format_tool(schema: dict) -> str:
    name = schema["name"]
    description = schema.get("description", "").strip()
    properties = schema.get("input_schema", {}).get("properties", {}) or {}
    required = schema.get("input_schema", {}).get("required", []) or []
    lines = [f"## {name}"]
    if description:
        lines.append(description)
    if properties:
        lines.append("Parameters:")
        for prop_name, spec in properties.items():
            lines.append(_format_param(prop_name, spec, required))
    lines.append("Example:")
    lines.append(_example_for(schema))
    return "\n".join(lines)


def build_tool_docs(tool_schemas: list[dict]) -> str:
    sections = [_FORMAT_HEADER.rstrip()]
    for schema in tool_schemas:
        sections.append("")
        sections.append(_format_tool(schema))
    return "\n".join(sections)
