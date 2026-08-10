# [desc] Parses session JSON messages into structured Block list for HTML rendering. [/desc]
# [desc] Parses session JSON messages into structured Block list for HTML rendering.
"""Parse session JSON (messages array) into Block sequence."""
from __future__ import annotations

import re

from .parser import AssistantText, Block, ToolCall, ToolResult, UserMessage

_TOOL_USE_RE = re.compile(
    r'<tool_use\s+name="[^"]*"\s+id="[^"]*">.*?</tool_use>',
    re.DOTALL,
)


def strip_tool_xml(text: str) -> str:
    """Remove <tool_use> XML blocks from assistant content, keep plain text."""
    cleaned = _TOOL_USE_RE.sub("", text).strip()
    return re.sub(r"\n{3,}", "\n\n", cleaned)


def parse_session_json(messages: list[dict]) -> list[Block]:
    """Convert session JSON messages list into a flat Block sequence."""
    blocks: list[Block] = []
    tool_name_map: dict[str, str] = {}

    for msg in messages:
        role = msg.get("role", "")

        if role == "user":
            content = msg.get("content", "")
            if isinstance(content, list):
                parts = [
                    b.get("text", "")
                    for b in content
                    if isinstance(b, dict) and b.get("type") == "text"
                ]
                content = "\n".join(parts)
            if content:
                blocks.append(UserMessage(content=content))

        elif role == "assistant":
            raw_content = msg.get("content", "")
            tool_calls = msg.get("tool_calls", [])

            plain_text = strip_tool_xml(raw_content) if tool_calls else raw_content
            if plain_text:
                blocks.append(AssistantText(content=plain_text))

            for tc in tool_calls:
                call_id = tc.get("id", "")
                name = tc.get("name", "")
                raw_input = tc.get("input", {})
                params = {k: str(v) for k, v in raw_input.items()}
                blocks.append(ToolCall(name=name, call_id=call_id, params=params))
                tool_name_map[call_id] = name

        elif role == "tool":
            call_id = msg.get("tool_call_id", "")
            content = msg.get("content", "")
            tool_name = msg.get("name", "") or tool_name_map.get(call_id, "")
            blocks.append(ToolResult(
                call_id=call_id,
                content=content,
                tool_name=tool_name,
            ))

    return blocks
