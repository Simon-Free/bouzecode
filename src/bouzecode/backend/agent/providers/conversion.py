# [desc] Converts neutral chat messages to Anthropic API format with XML tool serialization and caching. [/desc]
from __future__ import annotations

from .types import sanitize_tool_name  # noqa: F401 — used by anthropic_stream


def sanitize_messages(messages: list) -> list:
    result = list(messages)
    i = 0
    while i < len(result):
        m = result[i]
        if m.get("role") == "assistant" and m.get("tool_calls"):
            expected_ids = {tc["id"] for tc in m["tool_calls"]}
            found_ids = set()
            j = i + 1
            while j < len(result) and result[j].get("role") == "tool":
                found_ids.add(result[j].get("tool_call_id"))
                j += 1
            missing = expected_ids - found_ids
            if missing:
                insert_at = j
                for tc in m["tool_calls"]:
                    if tc["id"] in missing:
                        result.insert(insert_at, {
                            "role": "tool",
                            "tool_call_id": tc["id"],
                            "name": tc["name"],
                            "content": "[Tool result not available \u2014 execution was interrupted]",
                        })
                        insert_at += 1
            i = j if j > i + 1 else i + 1
        else:
            i += 1
    return result


def _find_current_loop_start(messages: list) -> int:
    """Return the index of the first user message in the current (last) user loop."""
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].get("role") != "user":
            continue
        if i == 0:
            return 0
        j = i - 1
        while j >= 0 and messages[j].get("role") == "tool":
            j -= 1
        if j >= 0 and messages[j].get("role") == "assistant":
            return i
    return 0


def messages_to_anthropic(messages: list, cache_last: bool = True, meth_delta: str = "") -> list:
    """Convert neutral messages -> Anthropic API format using the XML tool protocol.

    Tool calls and tool results become XML text inside plain text messages
    instead of typed tool_use/tool_result blocks.
    """
    from ...xml_tool_protocol import serialize_tool_call, serialize_tool_result
    messages = sanitize_messages(messages)
    result = []
    neutral_to_anth = {}
    i = 0
    while i < len(messages):
        m = messages[i]
        role = m["role"]

        if role == "user":
            neutral_to_anth[i] = len(result)
            result.append({"role": "user", "content": m["content"]})
            i += 1

        elif role == "assistant":
            neutral_to_anth[i] = len(result)
            text = m.get("content", "") or ""
            tcs = m.get("tool_calls", [])
            if tcs:
                xml_parts = [text] if text else []
                for tc in tcs:
                    xml_parts.append(serialize_tool_call({"name": tc.get("name", ""), "id": tc.get("id"), "input": tc.get("inputs", tc.get("input", {}))}))
                text = "\n".join(xml_parts)
            result.append({"role": "assistant", "content": text})
            i += 1
            # Gather tool results into a single user message
            tool_xmls = []
            while i < len(messages) and messages[i].get("role") == "tool":
                tm = messages[i]
                tool_xmls.append(serialize_tool_result(
                    tm["tool_call_id"], tm.get("content", "")
                ))
                i += 1
            if tool_xmls:
                result.append({"role": "user", "content": "\n".join(tool_xmls)})

        else:
            # system or other — skip
            i += 1

    # Place cache_control breakpoint on the last message of the PREVIOUS user loop
    if cache_last and len(result) >= 2:
        loop_start_neutral = _find_current_loop_start(messages)
        if loop_start_neutral > 0:
            # Find the anthropic index just before the current loop
            anchor_idx = neutral_to_anth.get(loop_start_neutral, 1) - 1
            if 0 <= anchor_idx < len(result):
                msg = dict(result[anchor_idx])
                content = msg.get("content", "")
                if isinstance(content, str):
                    msg["content"] = [
                        {"type": "text", "text": content, "cache_control": {"type": "ephemeral"}}
                    ]
                result[anchor_idx] = msg

    return result
