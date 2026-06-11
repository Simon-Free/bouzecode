"""OSS shim: /memory command — delegates to the flat memory/ package."""
from __future__ import annotations


def cmd_memory(args: str, config: dict) -> str | None:
    """Handle /memory [query|consolidate]."""
    try:
        from memory import memory_manager
        parts = args.strip().split(None, 1)
        sub = parts[0] if parts else ""

        if sub == "consolidate":
            getattr(memory_manager, "consolidate", lambda c: None)(config)
            from bouzecode.ui.ansi import ok
            ok("Memory consolidation complete.")
            return None
        elif sub == "":
            memories = getattr(memory_manager, "list_memories", lambda: [])()
            if not memories:
                from bouzecode.ui.ansi import info
                info("No memories stored.")
                return None
            return "\n".join(str(m) for m in memories[:20])
        else:
            # Search query
            results = getattr(memory_manager, "search", lambda q: [])(sub)
            if not results:
                from bouzecode.ui.ansi import info
                info(f"No memories matching: {sub}")
                return None
            return "\n".join(str(r) for r in results[:10])
    except ImportError:
        from bouzecode.ui.ansi import warn
        warn("Memory package not available.")
        return None
