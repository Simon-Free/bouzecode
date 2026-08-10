# [desc] Converts chat messages and tool schemas between neutral, OpenAI, and Anthropic API formats. [/desc]
from __future__ import annotations
import json

from providers.types import sanitize_tool_name


def tools_to_openai(tool_schemas: list) -> list:
    return [
        {
            "type": "function",
            "function": {
                "name":        t["name"],
                "description": t["description"],
                "parameters":  t["input_schema"],
            },
        }
        for t in tool_schemas
    ]


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


def messages_to_anthropic(messages: list) -> list:
    """Convert neutral messages → Anthropic API format using the XML tool protocol.

    Tool calls and tool results become XML text inside plain text messages
    instead of typed tool_use/tool_result blocks. Some upstream proxies mangle
    structured tool_use SSE events; rendering them as text bypasses that path.
    See xml_tool_protocol/README.md.
    """
    from xml_tool_protocol import serialize_tool_call, serialize_tool_result
    messages = sanitize_messages(messages)
    result = []
    i = 0
    while i < len(messages):
        m = messages[i]
        role = m["role"]

        if role == "user":
            result.append({"role": "user", "content": m["content"]})
            i += 1

        elif role == "assistant":
            text = m.get("content", "") or ""
            tcs = m.get("tool_calls", [])
            if tcs and "tool_use" not in text:
                tool_xml_parts = [serialize_tool_call(tc) for tc in tcs]
                joiner = "\n" if text else ""
                text = text + joiner + "\n".join(tool_xml_parts)
            result.append({"role": "assistant", "content": text})
            i += 1

        elif role == "tool":
            parts = []
            while i < len(messages) and messages[i]["role"] == "tool":
                t = messages[i]
                parts.append(serialize_tool_result(t["tool_call_id"], t["content"]))
                i += 1
            result.append({"role": "user", "content": "\n".join(parts)})

        else:
            i += 1

    return result


def messages_to_openai(messages: list, ollama_native_images: bool = False) -> list:
    result = []
    for m in messages:
        role = m["role"]

        if role == "user":
            content = m["content"]
            if ollama_native_images and m.get("images"):
                msg_out = {"role": "user", "content": content, "images": m["images"]}
            elif not ollama_native_images and m.get("images"):
                parts = [{"type": "text", "text": content}]
                for img_b64 in m["images"]:
                    parts.append({
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{img_b64}"},
                    })
                msg_out = {"role": "user", "content": parts}
            else:
                msg_out = {"role": "user", "content": content}
            result.append(msg_out)

        elif role == "assistant":
            msg: dict = {"role": "assistant", "content": m.get("content") or None}
            tcs = m.get("tool_calls", [])
            if tcs:
                msg["tool_calls"] = []
                for tc in tcs:
                    safe_name, corrupted = sanitize_tool_name(tc["name"])
                    tool_input = dict(tc["input"])
                    if corrupted is not None:
                        tool_input["_corrupted_name"] = corrupted
                    tc_msg = {
                        "id":   tc["id"],
                        "type": "function",
                        "function": {
                            "name":      safe_name,
                            "arguments": json.dumps(tool_input, ensure_ascii=False),
                        },
                    }
                    if tc.get("extra_content"):
                        tc_msg["extra_content"] = tc["extra_content"]
                    msg["tool_calls"].append(tc_msg)
            result.append(msg)

        elif role == "tool":
            result.append({
                "role":         "tool",
                "tool_call_id": m["tool_call_id"],
                "content":      m["content"],
            })

    return result
