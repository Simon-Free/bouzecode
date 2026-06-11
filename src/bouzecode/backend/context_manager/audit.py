# [desc] Builds the verbatim-audit note prepended to each turn so the model can decide what to GC. [/desc]
from __future__ import annotations


_ARGS_PREFERRED_KEY = {
    "Read": "file_path", "Edit": "file_path", "Write": "file_path",
    "NotebookEdit": "notebook_path",
    "Glob": "pattern", "Grep": "pattern",
    "Bash": "command",
    "WebFetch": "url", "WebSearch": "query",
}


def _summarize_args(tool_name: str, input_dict: dict, max_len: int = 60) -> str:
    if not input_dict:
        return ""
    val = input_dict.get(_ARGS_PREFERRED_KEY.get(tool_name, ""))
    if val is None:
        for v in input_dict.values():
            if isinstance(v, str) and v:
                val = v
                break
    if val is None:
        return ""
    val = str(val).replace("\n", " ")
    if len(val) > max_len:
        val = val[: max_len - 3] + "..."
    return val


def build_verbatim_audit_note(messages: list) -> str:
    """List every tool_result still kept verbatim with its token size.

    Each entry includes the tool's key arg (file_path, pattern, command…) so the
    model can correlate "MUST re-read X" notes with results already in context.
    """
    from ..agent.compaction import estimate_tokens
    args_by_id: dict[str, dict] = {}
    for message in messages:
        if message.get("role") != "assistant":
            continue
        for tc in message.get("tool_calls") or []:
            tc_id = tc.get("id")
            if tc_id:
                args_by_id[tc_id] = tc.get("input") or {}
    lines = []
    for message in messages:
        if message.get("role") != "tool":
            continue
        content = message.get("content", "")
        if isinstance(content, list):
            content = "".join(
                block.get("text", "") if isinstance(block, dict) else str(block)
                for block in content
            )
        tool_call_id = message.get("tool_call_id", "?")
        tool_name = message.get("name", "?")
        size = estimate_tokens([{"content": content}])
        args = _summarize_args(tool_name, args_by_id.get(tool_call_id, {}))
        suffix = f" {args}" if args else ""
        lines.append(f"- {tool_call_id} ({tool_name}{suffix}): {size} tk")
    if not lines:
        return ""
    return (
        "[Verbatim tool_results still in your context — trash any you've already consumed]\n"
        + "\n".join(lines)
        + "\n[/Verbatim audit]"
    )


def prepend_verbatim_audit(messages: list) -> list:
    """Prepend the verbatim audit note to the last user message, if any candidates remain."""
    note = build_verbatim_audit_note(messages)
    if not note:
        return messages
    result = list(messages)
    for i in range(len(result) - 1, -1, -1):
        if result[i].get("role") == "user":
            result[i] = dict(result[i])
            result[i]["content"] = note + "\n\n" + result[i]["content"]
            break
    return result
