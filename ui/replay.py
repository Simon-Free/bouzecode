# [desc] Replay saved conversation messages through the same renderers used during live streaming. [/desc]
"""Render a list of saved messages using the live conversation display engine.

Used by /history, /load, /resume — keeps a single rendering path so resumed
sessions look exactly like ongoing ones (Markdown text, formatted tool calls,
diffs) instead of the old `[i] ROLE: text[:200]` debug dump.
"""
from __future__ import annotations

from typing import Any, Iterable

from html_renderer import strip_tool_xml
from ui.ansi import clr, info
from ui.rendering import flush_response, stream_text
from ui.tool_display import print_tool_end, print_tool_start


def _block_type(block: Any) -> str:
    if isinstance(block, dict):
        return block.get("type", "")
    return getattr(block, "type", "")


def _block_get(block: Any, key: str, default: Any = "") -> Any:
    if isinstance(block, dict):
        return block.get(key, default)
    return getattr(block, key, default)


def _normalize_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if _block_type(block) == "text":
                parts.append(_block_get(block, "text", ""))
        return "".join(parts)
    return str(content) if content is not None else ""


def _normalize_tool_calls(message: dict) -> list[dict]:
    tool_calls = message.get("tool_calls") or []
    if tool_calls:
        return [
            {"id": tc.get("id", ""), "name": tc.get("name", ""), "input": tc.get("input", {})}
            for tc in tool_calls
        ]
    content = message.get("content")
    if isinstance(content, list):
        out = []
        for block in content:
            if _block_type(block) == "tool_use":
                out.append({
                    "id": _block_get(block, "id", ""),
                    "name": _block_get(block, "name", ""),
                    "input": _block_get(block, "input", {}),
                })
        return out
    return []


def _flatten_tool_result(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
            else:
                parts.append(_normalize_text(block) or str(block))
        return "".join(parts)
    return str(content) if content is not None else ""


def _collect_tool_results(messages: list[dict]) -> dict[str, str]:
    """Map tool_call_id -> result text, supporting both internal and Anthropic-native shapes."""
    out: dict[str, str] = {}
    for m in messages:
        role = m.get("role")
        if role == "tool":
            out[m.get("tool_call_id", "")] = _flatten_tool_result(m.get("content", ""))
        elif role == "user" and isinstance(m.get("content"), list):
            for block in m["content"]:
                if _block_type(block) == "tool_result":
                    out[_block_get(block, "tool_use_id", "")] = _flatten_tool_result(
                        _block_get(block, "content", "")
                    )
    return out


def _is_pure_tool_result_message(m: dict) -> bool:
    content = m.get("content")
    if not isinstance(content, list) or not content:
        return False
    return all(_block_type(b) == "tool_result" for b in content)


def _print_user_header(text: str) -> None:
    print()
    print(clr("\u256d\u2500 you ", "dim") + clr("\u25cb", "cyan")
          + clr(" " + "\u2500" * 40, "dim"))
    for line in (text.splitlines() or [""]):
        print(clr("  \u2502 ", "dim") + line)


def _print_assistant_header() -> None:
    print()
    print(clr("\u256d\u2500 bouz\u00e9code ", "dim") + clr("\u25cf", "green")
          + clr(" " + "\u2500" * 25, "dim"))


def replay_messages(messages: Iterable[dict]) -> None:
    msgs = list(messages)
    if not msgs:
        info("(empty conversation)")
        return

    results = _collect_tool_results(msgs)

    for m in msgs:
        role = m.get("role")
        if role == "user":
            if _is_pure_tool_result_message(m):
                continue
            _print_user_header(_normalize_text(m.get("content", "")))
        elif role == "assistant":
            _print_assistant_header()
            tool_calls = _normalize_tool_calls(m)
            raw_text = _normalize_text(m.get("content", ""))
            text = strip_tool_xml(raw_text) if tool_calls else raw_text
            if text:
                stream_text(text)
                flush_response()
            for tc in tool_calls:
                print_tool_start(tc["name"], tc["input"], verbose=False)
                print_tool_end(tc["name"], results.get(tc["id"], ""), verbose=False, duration=0.0)
