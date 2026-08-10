"""Call zoom service — returns full args + result for a tool call."""

from __future__ import annotations

from pathlib import Path

from .formatter import pretty_json, resolve_overflow_pointer


_MAX_DUMP_BYTES = 500 * 1024  # 500 Ko guard


def get_call_detail(
    messages: list[dict], call_id: str
) -> dict | None:
    """Find a tool call by id and return its full detail.

    Returns None if call_id not found.
    Returns dict with: name, args, result, is_error, overflow_resolved.
    """
    # Find the assistant message containing the call
    call_info = None
    for msg in messages:
        if msg.get("role") != "assistant":
            continue
        for tc in msg.get("tool_calls") or []:
            if tc.get("id") == call_id:
                call_info = tc
                break
        if call_info:
            break

    if call_info is None:
        return None

    name = call_info.get("name") or call_info.get(
        "function", {}
    ).get("name", "?")
    args = call_info.get("input") or call_info.get("arguments") or {}
    args_str = pretty_json(args)

    # Find the tool result
    result_text = ""
    is_error = False
    for msg in messages:
        if msg.get("role") == "tool" and msg.get("tool_call_id") == call_id:
            result_text = msg.get("content", "")
            is_error = bool(msg.get("is_error"))
            break

    # Resolve overflow pointer if present
    overflow_resolved = False
    overflow_path = resolve_overflow_pointer(result_text)
    if overflow_path:
        p = Path(overflow_path)
        if p.is_file():
            size = p.stat().st_size
            if size > _MAX_DUMP_BYTES:
                # Guard: head 200 / tail 50
                lines = p.read_text(encoding="utf-8", errors="replace").split("\n")
                total = len(lines)
                head_part = lines[:200]
                tail_part = lines[total - 50:] if total > 250 else []
                omitted = total - 200 - len(tail_part)
                result_text = "\n".join(head_part)
                if tail_part:
                    result_text += (
                        f"\n[... {omitted} lignes omises — "
                        f"fichier total: {size} octets, {total} lignes]\n"
                    )
                    result_text += "\n".join(tail_part)
                else:
                    result_text += (
                        f"\n[... fichier total: {size} octets, {total} lignes]"
                    )
            else:
                raw = p.read_text(encoding="utf-8", errors="replace")
                result_text = pretty_json(raw)
            overflow_resolved = True

    return {
        "call_id": call_id,
        "name": name,
        "args": args_str,
        "result": result_text,
        "is_error": is_error,
        "overflow_resolved": overflow_resolved,
    }


def format_call_plain(data: dict) -> str:
    """Render call detail as plain text."""
    parts: list[str] = []
    parts.append(f"═══ {data['name']} [{data['call_id']}] ═══\n")
    parts.append("── args ──")
    parts.append(data["args"])
    parts.append("")
    label = "résultat (ERREUR)" if data["is_error"] else "résultat"
    if data["overflow_resolved"]:
        label += " (overflow résolu)"
    parts.append(f"── {label} ──")
    parts.append(data["result"])
    return "\n".join(parts)
