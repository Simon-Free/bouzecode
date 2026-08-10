# [desc] Serializes tool calls and tool results into XML with CDATA escaping. [/desc]
"""Produces XML text for tool calls and tool results.

CDATA wrapping kicks in only when a value contains '<', '>' or '&'. Embedded
']]>' sequences are escaped using the canonical splitting trick:
    ]]>  →  ]]]]><![CDATA[>
Round-trip with the parser is guaranteed for any string value.
"""
from __future__ import annotations

import json
from typing import Any


def _needs_cdata(s: str) -> bool:
    return "<" in s or ">" in s or "&" in s


def _wrap_cdata(s: str) -> str:
    if "]]>" not in s:
        return f"<![CDATA[{s}]]>"
    return "<![CDATA[" + "]]]]><![CDATA[>".join(s.split("]]>")) + "]]>"


def _stringify(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (list, dict, tuple)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _serialize_value(value: Any) -> str:
    s = _stringify(value)
    return _wrap_cdata(s) if _needs_cdata(s) else s


def _escape_attr(s: str) -> str:
    return str(s).replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;")


def serialize_tool_call(tool_call: dict) -> str:
    name = _escape_attr(tool_call.get("name", ""))
    parts = [f'<tool_use name="{name}"']
    tool_id = tool_call.get("id")
    if tool_id:
        parts.append(f' id="{_escape_attr(tool_id)}"')
    parts.append(">")
    for key, value in tool_call.get("input", {}).items():
        parts.append(f'<param name="{_escape_attr(key)}">')
        parts.append(_serialize_value(value))
        parts.append("</param>")
    parts.append("</tool_use>")
    return "".join(parts)


def serialize_tool_result(tool_call_id: str, content: str) -> str:
    from ..agent.compaction import estimate_tokens
    body = _wrap_cdata(content) if _needs_cdata(content) else content
    size = estimate_tokens([{"content": content}])
    return f'<tool_result id="{_escape_attr(tool_call_id)}" tokens="{size}">{body}</tool_result>'
