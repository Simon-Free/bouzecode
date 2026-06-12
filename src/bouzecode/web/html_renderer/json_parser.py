# [desc] Parses session JSON messages into structured Block list for HTML rendering. [/desc]
"""Parse session JSON (messages array) into Block sequence."""
from __future__ import annotations

import re

from .parser import AssistantText, Block, SystemNotice, ToolCall, ToolResult, UserMessage

_ENFORCEMENT_RE = re.compile(r'⚠️\s*ENFORCEMENT')
_SYSTEM_EVENT_RE = re.compile(r'^\(System Automated Event\)')

# Permissive: matches <tool_use ...any attrs...>...</tool_use>
_TOOL_USE_RE = re.compile(r'<tool_use\b[^>]*>.*?</tool_use>', re.DOTALL)

# Matches "[Response from tool_use name="..." id="..."]" followed by content
# up to the next [Response from ...] header, next <tool_use, or end of string
_RESPONSE_BLOCK_RE = re.compile(
    r'\[Response from tool_use\s+name="[^"]*"\s+id="[^"]*"\]\n?'
    r'.*?'
    r'(?=\[Response from tool_use\s|<tool_use\b|\Z)',
    re.DOTALL,
)

_SKIP_TOOL_NAMES = {"_XmlParseError", "_InvalidToolName"}


_THINKING_BLOCK_RE = re.compile(
    r'^<thinking>[ \t]*\n.*?^</thinking>[ \t]*$|<thinking>[^\n]*?</thinking>',
    re.DOTALL | re.MULTILINE,
)


def strip_tool_xml(text: str) -> str:
    """Remove <tool_use> XML blocks and [Response from ...] blocks from assistant content."""
    # Protect thinking blocks from being stripped
    placeholders: list[str] = []

    def _save_thinking(m: re.Match) -> str:
        placeholders.append(m.group(0))
        return f"\x00THINKING_{len(placeholders) - 1}\x00"

    text_protected = _THINKING_BLOCK_RE.sub(_save_thinking, text)
    cleaned = _TOOL_USE_RE.sub("", text_protected)
    cleaned = _RESPONSE_BLOCK_RE.sub("", cleaned)
    # Restore thinking blocks
    for i, block in enumerate(placeholders):
        cleaned = cleaned.replace(f"\x00THINKING_{i}\x00", block)
    cleaned = cleaned.strip()
    return re.sub(r"\n{3,}", "\n\n", cleaned)


def parse_session_json(messages: list[dict]) -> list[Block]:
    """Convert session JSON messages list into a flat Block sequence."""
    blocks: list[Block] = []
    tool_name_map: dict[str, str] = {}
    skip_call_ids: set[str] = set()

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
                if _ENFORCEMENT_RE.search(content) or _SYSTEM_EVENT_RE.match(content):
                    blocks.append(SystemNotice(content=content))
                else:
                    blocks.append(UserMessage(content=content))

        elif role == "assistant":
            raw_content = msg.get("content", "")
            tool_calls = msg.get("tool_calls") or []

            plain_text = strip_tool_xml(raw_content) if tool_calls else raw_content
            if plain_text:
                blocks.append(AssistantText(content=plain_text))

            for tc in tool_calls:
                call_id = tc.get("id", "")
                name = tc.get("name", "")
                if name in _SKIP_TOOL_NAMES:
                    skip_call_ids.add(call_id)
                    continue
                raw_input = tc.get("input", {})
                params = {k: str(v) for k, v in raw_input.items()}
                blocks.append(ToolCall(name=name, call_id=call_id, params=params))
                tool_name_map[call_id] = name

        elif role == "tool":
            call_id = msg.get("tool_call_id", "")
            if call_id in skip_call_ids:
                continue
            content = msg.get("content", "")
            tool_name = msg.get("name", "") or tool_name_map.get(call_id, "")
            if tool_name in _SKIP_TOOL_NAMES:
                skip_call_ids.add(call_id)
                continue
            blocks.append(ToolResult(
                call_id=call_id,
                content=content,
                tool_name=tool_name,
            ))

    return blocks
