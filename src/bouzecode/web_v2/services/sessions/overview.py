# [desc] Builds structured per-turn overview of a session for the /overview endpoint. [/desc]
"""Build a structured overview of a session for the /overview endpoint.

Produces one entry per turn with trigger, assistant excerpt, tool call summary,
and success/failure markers. Designed to replace the heavy /blocks?plain=1 dump.
"""
from __future__ import annotations

import json

from .formatter import pretty_json, truncate_block


def build_overview(
    data: dict, key: str, after: int = 0, limit: int = 30
) -> dict:
    """Parse session data into header + turn summaries.

    Returns {"header": {...}, "turns": [...], "pagination": {...}}.
    """
    header = _build_header(data)
    turns = _extract_turns(data.get("messages") or [], key)

    # Pagination
    total_turns = len(turns)
    turns_page = turns[after: after + limit]

    return {
        "header": header,
        "turns": turns_page,
        "pagination": {
            "total": total_turns,
            "after": after,
            "limit": limit,
        },
    }


def format_plain(overview: dict, key: str) -> str:
    """Render overview dict as structured plain text."""
    lines: list[str] = []
    h = overview["header"]

    # Header block
    lines.append(f"=== Session: {key} ===")
    lines.append(f"Model: {h['model']}  |  Turns: {h['turn_count']}  |  State: {h['close_reason'] or 'open'}")
    lines.append(f"Tokens: {h['input_tokens']} in / {h['output_tokens']} out")
    if h["final_answer"]:
        fa_lines = h["final_answer"].split("\n")[:2]
        fa_preview = "\n  ".join(fa_lines)
        if len(h["final_answer"].split("\n")) > 2:
            fa_preview += "\n  [...]"
        lines.append(f"Final answer:\n  {fa_preview}")
    lines.append("")

    # Turns
    for turn in overview["turns"]:
        parts = [f"T{turn['index']}"]
        parts.append(f"[{turn['trigger']}]")
        if turn["assistant_excerpt"]:
            parts.append(turn["assistant_excerpt"])
        if turn["tool_calls"]:
            tc_str = ", ".join(turn["tool_calls"])
            parts.append(f"| {tc_str}")
        zoom = f"zoom: /api/sessions/{key}/turns/{turn['index']}"
        parts.append(f"({zoom})")
        lines.append("  ".join(parts))

    # Pagination note
    p = overview["pagination"]
    if p["after"] + p["limit"] < p["total"]:
        lines.append(f"\n[... showing {len(overview['turns'])}/{p['total']} turns, use ?after={p['after'] + p['limit']} for next page]")

    return "\n".join(lines)


def _build_header(data: dict) -> dict:
    return {
        "model": data.get("model", ""),
        "turn_count": data.get("turn_count", 0),
        "input_tokens": data.get("total_input_tokens", 0),
        "output_tokens": data.get("total_output_tokens", 0),
        "close_reason": data.get("close_reason", ""),
        "final_answer": data.get("final_answer", ""),
    }


def _extract_turns(messages: list[dict], key: str) -> list[dict]:
    """Group messages into logical turns.

    A turn starts at each assistant message. The trigger is determined by
    what precedes it (user message = 'user', nothing/tool = 'continue',
    enforcement markers, etc.).
    """
    turns: list[dict] = []
    turn_index = 0
    i = 0

    while i < len(messages):
        msg = messages[i]

        if msg["role"] == "assistant":
            turn_index += 1
            trigger = _determine_trigger(messages, i)
            excerpt = _extract_excerpt(msg.get("content", ""))
            tool_calls = _format_tool_calls(msg.get("tool_calls") or [], messages, i)

            turns.append({
                "index": turn_index,
                "trigger": trigger,
                "assistant_excerpt": excerpt,
                "tool_calls": tool_calls,
            })

        i += 1

    return turns


def _determine_trigger(messages: list[dict], assistant_idx: int) -> str:
    """Determine what triggered this assistant turn."""
    if assistant_idx == 0:
        return "user"

    # Look backwards for the preceding non-tool message
    for j in range(assistant_idx - 1, -1, -1):
        role = messages[j]["role"]
        if role == "user":
            content = messages[j].get("content", "")
            if "[ENFORCEMENT]" in content or "[enforcement]" in content:
                return "enforcement"
            return "user"
        if role == "assistant":
            # Previous turn's assistant — this is a continue
            return "continue"
        # role == "tool" — keep looking back

    return "continue"


def _extract_excerpt(content: str) -> str:
    """Extract first 2 lines of assistant text, truncated."""
    if not content:
        return ""
    lines = content.strip().split("\n")[:2]
    excerpt = " | ".join(line.strip() for line in lines if line.strip())
    if len(excerpt) > 120:
        excerpt = excerpt[:117] + "..."
    return excerpt


def _format_tool_calls(
    tool_calls: list[dict], messages: list[dict], assistant_idx: int
) -> list[str]:
    """Format tool calls as Name(main_arg) ✓/✗."""
    # Collect tool results that follow this assistant message
    results: list[dict] = []
    for j in range(assistant_idx + 1, len(messages)):
        if messages[j]["role"] == "tool":
            results.append(messages[j])
        else:
            break

    formatted: list[str] = []
    for k, tc in enumerate(tool_calls):
        name = tc.get("name", "?")
        # Extract main argument for display
        main_arg = _extract_main_arg(tc)
        display = f"{name}({main_arg})" if main_arg else f"{name}()"

        # Match with result
        if k < len(results):
            result = results[k]
            if result.get("is_error"):
                reason = (result.get("content", "") or "")[:60]
                display += f" ✗ {reason}"
            else:
                display += " ✓"
        formatted.append(display)

    return formatted


def _extract_main_arg(tc: dict) -> str:
    """Extract the main argument from a tool call for display."""
    raw_input = tc.get("input", "")
    if not raw_input:
        return ""
    try:
        args = json.loads(raw_input) if isinstance(raw_input, str) else raw_input
    except (json.JSONDecodeError, ValueError):
        return ""

    # Pick the most informative arg
    for key in ("file_path", "command", "pattern", "question", "content", "targets", "name"):
        if key in args:
            val = str(args[key])
            if len(val) > 50:
                val = val[:47] + "..."
            return val
    # Fallback: first value
    if args:
        val = str(next(iter(args.values())))
        if len(val) > 50:
            val = val[:47] + "..."
        return val
    return ""
