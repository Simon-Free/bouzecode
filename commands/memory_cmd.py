# [desc] CLI commands for searching/displaying memories and listing sub-agent tasks with background notifications. [/desc]
"""Memory and agent commands — extracted from bouzecode.py."""
from __future__ import annotations

from ui.ansi import clr, info, ok, err


def cmd_memory(args: str, _state, config) -> bool:
    from memory import search_memory, load_index
    from memory.scan import scan_all_memories, format_memory_manifest, memory_freshness_text

    stripped = args.strip()

    # /memory consolidate  — extract long-term memories from current session
    if stripped == "consolidate":
        from memory import consolidate_session
        msgs = _state.get("messages", [])
        info("  Analyzing session for long-term memories…")
        saved = consolidate_session(msgs, config)
        if saved:
            info(f"  ✓ Consolidated {len(saved)} memory/memories: {', '.join(saved)}")
        else:
            info("  Nothing new worth saving (session too short, or nothing extractable).")
        return True

    if stripped:
        results = search_memory(stripped)
        if not results:
            info(f"No memories matching '{stripped}'")
            return True
        info(f"  {len(results)} result(s) for '{stripped}':")
        for m in results:
            conf_tag = f" conf:{m.confidence:.0%}" if m.confidence < 1.0 else ""
            src_tag = f" src:{m.source}" if m.source and m.source != "user" else ""
            info(f"  [{m.type:9s}|{m.scope:7s}] {m.name}{conf_tag}{src_tag}: {m.description}")
            info(f"    {m.content[:120]}{'...' if len(m.content) > 120 else ''}")
        return True

    # Show manifest with age/freshness
    headers = scan_all_memories()
    if not headers:
        info("No memories stored. The model saves memories via MemorySave.")
        return True
    info(f"  {len(headers)} memory/memories (newest first):")
    for h in headers:
        fresh_warn = "  ⚠ stale" if memory_freshness_text(h.mtime_s) else ""
        tag = f"[{h.type or '?':9s}|{h.scope:7s}]"
        info(f"  {tag} {h.filename}{fresh_warn}")
        if h.description:
            info(f"    {h.description}")
    return True


def cmd_agents(_args: str, _state, config) -> bool:
    try:
        from multi_agent.tools import get_agent_manager
        mgr = get_agent_manager()
        tasks = mgr.list_tasks()
        if not tasks:
            info("No sub-agent tasks.")
            return True
        info(f"  {len(tasks)} sub-agent task(s):")
        for t in tasks:
            preview = t.prompt[:50] + ("..." if len(t.prompt) > 50 else "")
            wt_info = f"  branch:{t.worktree_branch}" if t.worktree_branch else ""
            info(f"  {t.id} [{t.status:9s}] name={t.name}{wt_info}  {preview}")
    except Exception:
        info("Sub-agent system not initialized.")
    return True


def _print_background_notifications():
    """Print notifications for newly completed background agent tasks.

    Called before each user prompt so the user sees results without polling.
    """
    try:
        from multi_agent.tools import get_agent_manager
        mgr = get_agent_manager()
    except Exception:
        return

    if not hasattr(_print_background_notifications, "_seen"):
        _print_background_notifications._seen = set()

    for task in mgr.list_tasks():
        if task.id in _print_background_notifications._seen:
            continue
        if task.status in ("completed", "failed", "cancelled"):
            _print_background_notifications._seen.add(task.id)
            icon = "✓" if task.status == "completed" else "✗"
            color = "green" if task.status == "completed" else "red"
            branch_info = f" [branch: {task.worktree_branch}]" if task.worktree_branch else ""
            print(clr(
                f"\n  {icon} Background agent '{task.name}' {task.status}{branch_info}",
                color, "bold"
            ))
            if task.result:
                preview = task.result[:200] + ("..." if len(task.result) > 200 else "")
                print(clr(f"    {preview}", "dim"))
            print()
