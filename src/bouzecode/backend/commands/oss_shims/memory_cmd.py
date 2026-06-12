"""OSS shim: /memory command — delegates to the flat memory/ package."""
from __future__ import annotations


def cmd_memory(args: str, config: dict) -> str | None:
    """Handle /memory [list|search <query>|consolidate]."""
    try:
        from memory.store import load_entries
        from memory.context import find_relevant_memories

        parts = args.strip().split(None, 1)
        sub = parts[0] if parts else ""

        if sub == "consolidate":
            from bouzecode.ui.ansi import info
            info("Memory consolidation: use MemorySave tool for new entries.")
            return None
        elif sub in ("", "list"):
            entries = []
            for scope in ("user", "project"):
                entries.extend(load_entries(scope))
            if not entries:
                from bouzecode.ui.ansi import info
                info("No memories stored.")
                return None
            lines = [f"{len(entries)} memory/memories:"]
            for e in entries[:20]:
                lines.append(f"  [{e.scope:7s}] {e.name}")
                if e.description:
                    lines.append(f"    {e.description}")
            return "\n".join(lines)
        else:
            # Search query
            query = args.strip()
            results = find_relevant_memories(query)
            if not results:
                from bouzecode.ui.ansi import info
                info(f"No memories matching: {query}")
                return None
            lines = [f"Found {len(results)} result(s):"]
            for r in results[:10]:
                lines.append(f"  {r.name}: {r.description or '(no description)'}")
            return "\n".join(lines)
    except ImportError:
        from bouzecode.ui.ansi import warn
        warn("Memory package not available.")
        return None
