"""Turn view service — formats a single turn for the zoom endpoint."""

from __future__ import annotations

import json
import re
import textwrap

from .formatter import pretty_json, truncate_block

_THINKING_RE = re.compile(
    r"<thinking>\s*\n?(.*?)\n?\s*</thinking>", re.DOTALL
)


def _split_into_turns(messages: list[dict]) -> list[dict]:
    """Split messages into turns (same logic as overview._extract_turns).

    Each turn = assistant message + following tool results.
    Returns list of {"assistant": msg, "tool_results": [msg, ...]}.
    """
    turns: list[dict] = []
    i = 0
    while i < len(messages):
        msg = messages[i]
        if msg.get("role") == "assistant":
            turn = {"assistant": msg, "tool_results": []}
            i += 1
            # Collect following tool results
            while i < len(messages) and messages[i].get("role") == "tool":
                turn["tool_results"].append(messages[i])
                i += 1
            turns.append(turn)
        else:
            i += 1
    return turns


def _format_thinking(content: str, full: bool = False) -> str | None:
    """Extract and format thinking block."""
    m = _THINKING_RE.search(content)
    if not m:
        return None
    thinking_text = m.group(1)
    lines = thinking_text.split("\n")
    if full:
        return f"[thinking — {len(lines)} lignes]\n{thinking_text}"
    # Summary: size + first 3 lines
    preview = "\n".join(lines[:3])
    return f"[thinking — {len(lines)} lignes]\n{preview}"


def _strip_thinking(content: str) -> str:
    """Remove thinking block from assistant content."""
    return _THINKING_RE.sub("", content).strip()


def _format_tool_call(
    tc: dict, tool_results: list[dict], key: str
) -> dict:
    """Format a single tool call with args + result."""
    call_id = tc.get("id", "")
    name = tc.get("name") or tc.get("function", {}).get("name", "?")
    args = tc.get("input") or tc.get("arguments") or {}

    # Pretty-print args
    args_str = pretty_json(args)
    # Truncate arg values > 30 lines
    if isinstance(args, dict):
        truncated_args = {}
        for k, v in args.items():
            v_str = str(v)
            v_lines = v_str.split("\n")
            if len(v_lines) > 30:
                v_str = "\n".join(v_lines[:30]) + \
                    f"\n[... {len(v_lines) - 30} lignes omises" \
                    f" — zoom: /api/sessions/{key}/calls/{call_id}]"
                truncated_args[k] = v_str
            else:
                truncated_args[k] = v
        args_str = pretty_json(truncated_args)

    # Find matching result
    result_text = ""
    is_error = False
    for tr in tool_results:
        if tr.get("tool_call_id") == call_id:
            result_text = tr.get("content", "")
            is_error = bool(tr.get("is_error"))
            break

    zoom_hint = f"/api/sessions/{key}/calls/{call_id}"
    result_display = truncate_block(
        result_text, head=40, tail=10,
        zoom_hint=zoom_hint, is_error=is_error,
    )

    return {
        "call_id": call_id,
        "name": name,
        "args": args_str,
        "result": result_display,
        "is_error": is_error,
    }


def format_turn_view(
    messages: list[dict],
    key: str,
    turn_n: int,
    thinking: bool = False,
) -> dict | None:
    """Format turn N for display.

    Returns None if turn_n is out of range.
    Returns dict with: assistant_content, thinking, tool_calls.
    """
    turns = _split_into_turns(messages)
    if turn_n < 1 or turn_n > len(turns):
        return None

    turn = turns[turn_n - 1]
    assistant_msg = turn["assistant"]
    content = assistant_msg.get("content", "")

    # Thinking
    thinking_display = _format_thinking(content, full=thinking)
    visible_content = _strip_thinking(content)

    # Tool calls
    raw_calls = assistant_msg.get("tool_calls") or []
    formatted_calls = [
        _format_tool_call(tc, turn["tool_results"], key)
        for tc in raw_calls
    ]

    return {
        "turn_index": turn_n,
        "assistant_content": visible_content,
        "thinking": thinking_display,
        "tool_calls": formatted_calls,
    }


def format_turn_plain(data: dict) -> str:
    """Render a turn view dict as plain text."""
    parts: list[str] = []

    parts.append(f"═══ Tour {data['turn_index']} ═══\n")

    if data.get("thinking"):
        parts.append(data["thinking"])
        parts.append("")

    parts.append(data["assistant_content"])
    parts.append("")

    for tc in data.get("tool_calls", []):
        parts.append(f"── {tc['name']} [{tc['call_id']}] ──")
        parts.append(tc["args"])
        if tc["result"]:
            parts.append(f"→ résultat{' (ERREUR)' if tc['is_error'] else ''}:")
            parts.append(tc["result"])
        parts.append("")

    return "\n".join(parts)
