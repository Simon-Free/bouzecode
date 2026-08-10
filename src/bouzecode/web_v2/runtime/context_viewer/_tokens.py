# [desc] Pure token/brief helpers extracted from items.py: token estimation, tool_call briefs, and index build. [/desc]
"""Pure helpers extracted from items.py: token estimation, tool_call briefs, index build. No backend imports."""
import json

_PREFERRED_KEYS = {
    "Read": "file_path", "Edit": "file_path", "Write": "file_path",
    "Bash": "command", "Grep": "pattern", "Glob": "pattern",
    "WebFetch": "url", "WebSearch": "query", "Skill": "name",
    "Snippet": "file_path", "MemorySave": "name", "NotebookEdit": "notebook_path",
    "Agent": "prompt", "GetFolderDescription": "folder_path",
}
TOKEN_DIVISOR = 3.5


def estimate_tokens(text: str | None) -> int:
    if not text:
        return 0
    return max(1, int(len(text) / TOKEN_DIVISOR))


def message_text(msg: dict) -> str:
    content = msg.get("content", "")
    if isinstance(content, list):
        return " ".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in content)
    return content or ""


def tool_call_brief(name: str, tool_input: dict, max_len: int = 80) -> str:
    key = _PREFERRED_KEYS.get(name)
    value = tool_input.get(key) if key else None
    if value is None:
        for candidate in tool_input.values():
            if isinstance(candidate, str) and candidate:
                value = candidate
                break
    if not value:
        return ""
    value = str(value).replace("\n", " ").strip()
    return value[:max_len - 1] + "\u2026" if len(value) > max_len else value


def serialize_tool_call(tool_call: dict) -> str:
    """Approximate on-wire payload size of a single tool_call."""
    return json.dumps(tool_call.get("input") or {}, ensure_ascii=False) + (tool_call.get("name", "") or "")


def build_tool_call_index(messages: list[dict]) -> dict[str, tuple[str, dict]]:
    """Map tool_call_id -> (tool_name, tool_input) across all assistant turns."""
    index: dict[str, tuple[str, dict]] = {}
    for msg in messages:
        if msg.get("role") != "assistant":
            continue
        for tc in msg.get("tool_calls") or []:
            call_id = tc.get("id", "")
            if call_id:
                index[call_id] = (tc.get("name", ""), tc.get("input") or {})
    return index
