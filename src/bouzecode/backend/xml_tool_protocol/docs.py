# [desc] Generates system-prompt documentation and XML examples for available tools in the protocol. [/desc]
# [desc] Generates system-prompt documentation and XML examples for available tools in the protocol. [/desc]
"""Builds the system-prompt section that teaches the LLM the XML tool protocol."""
from __future__ import annotations

import json
from typing import Any

from ..xml_tool_protocol.serializer import serialize_tool_call

_FORMAT_HEADER = """\
# Tool calls — XML protocol

Emit tools as XML, inside ONE `<tool_calls>` batch that ends your message:
<tool_calls>
<tool_use name="ToolName" id="x1"><param name="key">value</param></tool_use>
</tool_calls>

Rules:
- This XML is the ONLY way to call a tool. A fenced code block holding a JSON object with a
  name/arguments field, a bold "Tool call" heading, or any prose describing a call: executes NOTHING.
- NEVER write the output of a tool yourself — any result you produce is a hallucination.
  Results only ever come back from the harness, in the NEXT message.
- Generation STOPS at `</tool_calls>`: the stream is cut there, so nothing you write after it exists.
  Put every call of the turn inside the batch, and close it as the last thing you emit.
- `id` is a short identifier you choose (e.g. r1, w2). Wrap values in CDATA if they contain `<`, `>` or `&`.
- Emit multiple tool blocks in the same batch to run them in parallel.
- The XML is internal — never echo this markup in your prose.

Universal scheduling params (available on EVERY tool — not repeated below).
They are ATTRIBUTES on the opening tag, exactly like `name` and `id` — never `<param>` elements:
- `tool_call_alias="w1"` (string, optional): names this call so another one can wait for it.
- `depends_on=["w1"]` (JSON array of strings, optional): aliases/ids that must finish before this tool runs.
  Write the brackets UNQUOTED, as above. Chain tools in a single turn instead of spending a turn per step.

Worked example — write a file, then read it back only once the write has completed:
<tool_use name="Write" id="w1" tool_call_alias="w1"><param name="file_path">notes.txt</param><param name="content">hello</param></tool_use>
<tool_use name="Bash" id="b1" depends_on=["w1"]><param name="command">cat notes.txt</param></tool_use>

Available tools (each section ends with a parsable example):
"""

_SCHEDULING_PARAM_NAMES = {"tool_call_alias", "depends_on"}


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
    all_properties = schema.get("input_schema", {}).get("properties", {}) or {}
    properties = {k: v for k, v in all_properties.items() if k not in _SCHEDULING_PARAM_NAMES}
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


_INDEX_HEADER = (
    "Other tools (signature + purpose; same XML protocol, `?` marks an optional param — "
    "their domain doc, when one exists, details them):"
)


def _index_line(schema: dict) -> str:
    """One line per tool: ``- name(param: type, opt?: type) — first sentence``."""
    properties = schema.get("input_schema", {}).get("properties", {}) or {}
    required = schema.get("input_schema", {}).get("required", []) or []
    params = ", ".join(
        f"{name}{'' if name in required else '?'}: {spec.get('type', 'string')}"
        for name, spec in properties.items() if name not in _SCHEDULING_PARAM_NAMES
    )
    first_sentence = schema.get("description", "").strip().split("\n")[0].split(". ")[0]
    purpose = f" — {first_sentence.rstrip('.')}." if first_sentence else ""
    return f"- {schema['name']}({params}){purpose}"


def build_tool_docs(tool_schemas: list[dict], full_doc_names=None) -> str:
    """Document every tool in full, or only ``full_doc_names`` with the rest indexed.

    An agent with a large toolset (Focus: ~120 tools, ~24k tokens of docs per call)
    passes its core set: those keep their full section, the others a one-line index
    entry so they stay callable without paying their full documentation each call.
    """
    sections = [_FORMAT_HEADER.rstrip()]
    indexed = []
    for schema in tool_schemas:
        if full_doc_names is not None and schema["name"] not in full_doc_names:
            indexed.append(_index_line(schema))
            continue
        sections.append("")
        sections.append(_format_tool(schema))
    if indexed:
        sections += ["", _INDEX_HEADER, *indexed]
    return "\n".join(sections)
