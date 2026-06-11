# [desc] Converters for OpenRouter native function-calling: tool schemas, message format, streamed tool_call deltas. [/desc]
"""Native (OpenAI function-calling) helpers for the OpenRouter backend.

Weaker models hand-write XML tool calls unreliably (unclosed blocks, self-closing
params, CDATA mistakes). Native function-calling sends tools via the API `tools`
param and receives structured `tool_calls` deltas, removing that whole failure
class. These helpers convert to/from the neutral message format the agent loop uses.
"""
from __future__ import annotations
import json

from ..conversion import sanitize_messages

_SCHEDULING_PROPS = {
    "depends_on": {
        "type": "array",
        "items": {"type": "string"},
        "description": "Aliases/IDs that must finish before this tool runs.",
    },
    "tool_call_alias": {
        "type": "string",
        "description": "Alias for this call, referenced by others via depends_on.",
    },
}


def tool_schemas_to_openai(tool_schemas: list) -> list:
    tools = []
    for schema in tool_schemas or []:
        params = dict(schema.get("input_schema") or {})
        params.setdefault("type", "object")
        props = dict(params.get("properties") or {})
        for name, spec in _SCHEDULING_PROPS.items():
            props.setdefault(name, spec)
        params["properties"] = props
        tools.append({
            "type": "function",
            "function": {
                "name": schema["name"],
                "description": schema.get("description", ""),
                "parameters": params,
            },
        })
    return tools


def _content_to_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            b.get("text", "") for b in content
            if isinstance(b, dict) and b.get("type") == "text"
        )
    return str(content)


def messages_to_openai_native(messages: list, system: str) -> list:
    msgs = sanitize_messages(messages)
    out = [{"role": "system", "content": system}]
    i = 0
    while i < len(msgs):
        m = msgs[i]
        role = m.get("role")
        if role == "user":
            out.append({"role": "user", "content": _content_to_text(m["content"])})
            i += 1
        elif role == "assistant":
            tcs = m.get("tool_calls", [])
            entry = {
                "role": "assistant",
                "content": _content_to_text(m.get("content", "")) or None,
            }
            if tcs:
                entry["tool_calls"] = [
                    {
                        "id": tc.get("id"),
                        "type": "function",
                        "function": {
                            "name": tc.get("name", ""),
                            "arguments": json.dumps(
                                tc.get("inputs", tc.get("input", {})) or {}
                            ),
                        },
                    }
                    for tc in tcs
                ]
            out.append(entry)
            i += 1
            while i < len(msgs) and msgs[i].get("role") == "tool":
                tm = msgs[i]
                out.append({
                    "role": "tool",
                    "tool_call_id": tm["tool_call_id"],
                    "content": tm.get("content", ""),
                })
                i += 1
        else:
            i += 1
    return out


def accumulate_tool_call_deltas(deltas: list, tool_buf: dict) -> None:
    for d in deltas or []:
        idx = d.get("index", 0)
        slot = tool_buf.setdefault(idx, {"id": None, "name": "", "args": ""})
        if d.get("id"):
            slot["id"] = d["id"]
        fn = d.get("function") or {}
        if fn.get("name"):
            slot["name"] += fn["name"]
        if fn.get("arguments"):
            slot["args"] += fn["arguments"]


def finalize_tool_calls(tool_buf: dict) -> list:
    out = []
    for idx in sorted(tool_buf):
        slot = tool_buf[idx]
        if not slot["name"]:
            continue
        tid = slot["id"] or f"or_{idx}"
        raw = slot["args"].strip()
        try:
            inp = json.loads(raw) if raw else {}
        except (json.JSONDecodeError, ValueError) as e:
            out.append({
                "id": tid,
                "name": "_ToolArgsParseError",
                "input": {"_error": str(e), "_tool": slot["name"], "_raw": raw[:500]},
            })
            continue
        if not isinstance(inp, dict):
            inp = {"_value": inp}
        out.append({"id": tid, "name": slot["name"], "input": inp})
    return out
