"""OSS shim: /mcp command — delegates to the flat mcp/ package."""
from __future__ import annotations


def cmd_mcp(args: str, config: dict) -> str | None:
    """Handle /mcp [list|reload|add|remove]."""
    try:
        from mcp import mcp_manager
        parts = args.strip().split(None, 1)
        sub = parts[0] if parts else "list"
        rest = parts[1] if len(parts) > 1 else ""

        if sub == "list":
            servers = getattr(mcp_manager, "list_servers", lambda: [])()
            if not servers:
                from bouzecode.ui.ansi import info
                info("No MCP servers configured.")
                return None
            lines = [f"  {s}" for s in servers]
            return "MCP servers:\n" + "\n".join(lines)
        elif sub == "reload":
            getattr(mcp_manager, "reload", lambda: None)()
            from bouzecode.ui.ansi import ok
            ok("MCP servers reloaded.")
            return None
        elif sub == "add":
            from bouzecode.ui.ansi import info
            info(f"MCP add: {rest}")
            return None
        elif sub == "remove":
            from bouzecode.ui.ansi import info
            info(f"MCP remove: {rest}")
            return None
        else:
            from bouzecode.ui.ansi import err
            err(f"Unknown /mcp subcommand: {sub}")
            return None
    except ImportError:
        from bouzecode.ui.ansi import warn
        warn("MCP package not available.")
        return None
