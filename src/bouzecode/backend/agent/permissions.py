# [desc] Permission checking and denial propagation for tool calls based on config modes. [/desc]
from __future__ import annotations

import os


def _propagate_denials(
    all_tcs: list[dict],
    permitted_map: dict[str, bool],
    denied_results: dict[str, str],
) -> None:
    denied_ids = {tid for tid, ok in permitted_map.items() if not ok}
    if not denied_ids:
        return
    alias_to_id: dict[str, str] = {}
    for tc in all_tcs:
        alias = tc["input"].get("tool_call_alias")
        if alias:
            alias_to_id[alias] = tc["id"]
    deps_of: dict[str, set[str]] = {}
    for tc in all_tcs:
        raw = tc["input"].get("depends_on") or []
        if isinstance(raw, str):
            raw = [raw] if raw else []
        deps_of[tc["id"]] = {alias_to_id.get(d, d) for d in raw}
    changed = True
    while changed:
        changed = False
        for tc in all_tcs:
            if permitted_map.get(tc["id"], True) and (deps_of.get(tc["id"], set()) & denied_ids):
                permitted_map[tc["id"]] = False
                denied_ids.add(tc["id"])
                denied_results[tc["id"]] = "Skipped: a dependency was denied"
                changed = True


def _check_permission(tc: dict, config: dict) -> bool:
    perm_mode = config.get("permission_mode", "auto")
    name = tc["name"]

    if name in ("EnterPlanMode", "ExitPlanMode"):
        return True
    if name in ("_InvalidToolName", "_XmlParseError"):
        return True
    if perm_mode == "accept-all":
        return True
    if perm_mode == "manual":
        return False

    if perm_mode == "plan":
        # Methodology/Snippet are working-memory tools, not file writes. They MUST
        # stay allowed in plan mode, otherwise per-turn enforcement (which requires
        # a Methodology every turn) can never be satisfied → infinite bounce loop.
        if name in ("Methodology", "Snippet"):
            return True
        if name in ("Write", "Edit"):
            plan_file = config.get("_plan_file", "")
            target = tc["input"].get("file_path", "")
            if plan_file and target and \
               os.path.normpath(target) == os.path.normpath(plan_file):
                return True
            return False
        if name == "NotebookEdit":
            return False
        if name == "Bash":
            from ..tools import _is_safe_bash
            return _is_safe_bash(tc["input"].get("command", ""))
        from ..core.tool_registry import get_tool
        tool_def = get_tool(name)
        if tool_def and not tool_def.read_only:
            return False
        return True

    if name in ("Read", "Glob", "Grep", "WebFetch", "WebSearch"):
        return True
    if name == "Bash":
        from ..tools import _is_safe_bash
        return _is_safe_bash(tc["input"].get("command", ""))
    return False


def _permission_desc(tc: dict) -> str:
    name = tc["name"]
    inp = tc["input"]
    if name == "Bash":   return f"Run: {inp.get('command', '')}"
    if name == "Write":  return f"Write to: {inp.get('file_path', '')}"
    if name == "Edit":   return f"Edit: {inp.get('file_path', '')}"
    return f"{name}({list(inp.values())[:1]})"
