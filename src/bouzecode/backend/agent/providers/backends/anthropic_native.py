# [desc] Native Anthropic tool_use: schema conversion, wire messages with typed blocks, streamed input_json_delta accumulation. [/desc]
"""Native `tool_use` helpers for the Anthropic backend.

The XML tool protocol (`xml_tool_protocol/`) exists because a corporate LLM gateway
was assumed to mangle native `tool_use` SSE blocks. That assumption was re-tested on
2026-07-27 and refuted. These helpers are the native alternative: schemas go through
the API `tools` param and arguments come back as server-produced JSON, which removes
the whole XML-parsing failure class.

Only the WIRE changes. The neutral message format bouzecode persists (role/
tool_calls/tool_call_id) is untouched, so compaction, minimal_payload, snippet_wire
and the HTML renderer keep working on exactly what they worked on before.
"""
from __future__ import annotations
import json

from ..conversion import sanitize_messages, _find_current_loop_start
from .openrouter_native import _SCHEDULING_PROPS

# Anthropic rejects empty text/tool_result content; use a visible stand-in instead.
_EMPTY_CONTENT_STUB = "(no output)"


def tool_schemas_to_anthropic(tool_schemas: list) -> list:
    """Neutral tool schemas -> Anthropic `tools`, scheduling params included.

    `depends_on` and `tool_call_alias` are bouzecode scheduling params, not real
    tool arguments; they must be declared on every tool or the model cannot express
    a dependency. `dag.py` pops them straight out of the parsed arguments, so in
    native mode they are ordinary JSON keys and need no special handling.
    """
    tools = []
    for schema in tool_schemas or []:
        params = dict(schema.get("input_schema") or {})
        params.setdefault("type", "object")
        props = dict(params.get("properties") or {})
        for name, spec in _SCHEDULING_PROPS.items():
            props.setdefault(name, spec)
        params["properties"] = props
        tools.append({
            "name": schema["name"],
            "description": schema.get("description", ""),
            "input_schema": params,
        })
    return tools


def _tool_use_block(tool_call: dict) -> dict:
    return {
        "type": "tool_use",
        "id": tool_call.get("id"),
        "name": tool_call.get("name", ""),
        "input": tool_call.get("inputs", tool_call.get("input", {})) or {},
    }


def _tool_result_block(tool_msg: dict) -> dict:
    """One neutral `role: tool` message -> one `tool_result` block.

    An image result (the `__BOUZE_IMAGE__:<mime>:<b64>` sentinel produced by Read on
    an image) becomes a real image block INSIDE the tool_result. The XML path had to
    emit it as a separate user block, which left the tool_use unanswered; native
    keeps the pairing the API requires.
    """
    content = tool_msg.get("content", "") or ""
    if content.startswith("__BOUZE_IMAGE__:"):
        _, media_type, b64 = content.split(":", 2)
        content = [{"type": "image",
                    "source": {"type": "base64", "media_type": media_type, "data": b64}}]
    return {
        "type": "tool_result",
        "tool_use_id": tool_msg["tool_call_id"],
        "content": content or _EMPTY_CONTENT_STUB,
    }


def _mark_cache_breakpoint(result: list, index: int) -> None:
    message = dict(result[index])
    content = message.get("content", "")
    if isinstance(content, str):
        content = [{"type": "text", "text": content or _EMPTY_CONTENT_STUB}]
    else:
        content = [dict(block) for block in content]
    content[-1] = {**content[-1], "cache_control": {"type": "ephemeral"}}
    message["content"] = content
    result[index] = message


def messages_to_anthropic_native(messages: list, cache_last: bool = True) -> list:
    """Neutral messages -> Anthropic wire using typed tool_use/tool_result blocks."""
    messages = sanitize_messages(messages)
    result: list = []
    neutral_to_anth: dict[int, int] = {}
    i = 0
    while i < len(messages):
        message = messages[i]
        role = message["role"]
        if role != "assistant":
            if role == "user":
                neutral_to_anth[i] = len(result)
                result.append({"role": "user", "content": message["content"]})
            i += 1
            continue

        neutral_to_anth[i] = len(result)
        blocks = []
        text = message.get("content", "") or ""
        if text.strip():
            blocks.append({"type": "text", "text": text})
        declared = set()
        for tool_call in message.get("tool_calls", []) or []:
            blocks.append(_tool_use_block(tool_call))
            declared.add(tool_call.get("id"))
        i += 1

        tool_msgs = []
        while i < len(messages) and messages[i].get("role") == "tool":
            tool_msgs.append(messages[i])
            i += 1
        # build_minimal_payload can drop the assistant message that owned the
        # tool_calls and keep only its results. Anthropic rejects a tool_result
        # whose tool_use_id has no matching tool_use in the preceding assistant
        # message, so re-declare the missing ones (same fix as the OpenAI path).
        for tool_msg in tool_msgs:
            tool_id = tool_msg.get("tool_call_id")
            if tool_id and tool_id not in declared:
                blocks.append({"type": "tool_use", "id": tool_id,
                               "name": tool_msg.get("name") or "Methodology", "input": {}})
                declared.add(tool_id)

        result.append({"role": "assistant",
                       "content": blocks or [{"type": "text", "text": "."}]})
        if tool_msgs:
            result.append({"role": "user",
                           "content": [_tool_result_block(t) for t in tool_msgs]})

    if cache_last and len(result) >= 2:
        loop_start = _find_current_loop_start(messages)
        if loop_start > 0:
            anchor = neutral_to_anth.get(loop_start, 1) - 1
            if 0 <= anchor < len(result):
                _mark_cache_breakpoint(result, anchor)
    return result


class NativeToolUseAccumulator:
    """Accumulates streamed `tool_use` content blocks, keyed by block index.

    The API interleaves concurrent blocks: the re-test observed three parallel
    calls whose `input_json_delta` events arrive mixed together, distinguished only
    by `index`. Each index therefore accumulates its own argument JSON, which is
    parsed once `content_block_stop` closes the block.
    """

    def __init__(self) -> None:
        self._open: dict[int, dict] = {}

    def start(self, index: int, block_id: str, name: str) -> None:
        self._open[index] = {"id": block_id, "name": name, "args": ""}

    def delta(self, index: int, partial_json: str) -> None:
        block = self._open.get(index)
        if block is not None:
            block["args"] += partial_json or ""

    def stop(self, index: int) -> dict | None:
        """Close one block and return its finished tool call, or None if `index`
        was a text/thinking block."""
        block = self._open.pop(index, None)
        return _finalize(index, block) if block else None

    def finalize(self) -> list:
        """Tool calls left open by a truncated stream, in index order."""
        pending = [(idx, self._open.pop(idx)) for idx in sorted(self._open)]
        return [_finalize(idx, block) for idx, block in pending]


def _finalize(index: int, block: dict) -> dict:
    tool_id = block["id"] or f"ant_{index}"
    raw = (block["args"] or "").strip()
    if not raw:
        return {"id": tool_id, "name": block["name"], "input": {}}
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, ValueError) as exc:
        # A truncated block stays localised: only this call fails, the sibling
        # blocks and the visible text are untouched.
        return {"id": tool_id, "name": "_ToolArgsParseError",
                "input": {"_error": str(exc), "_tool": block["name"], "_raw": raw[:500]}}
    if not isinstance(parsed, dict):
        parsed = {"_value": parsed}
    return {"id": tool_id, "name": block["name"], "input": parsed}
