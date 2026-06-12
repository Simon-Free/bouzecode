"""OSS shim: /mcp command — delegates to the flat mcp/ package."""
from __future__ import annotations

import json


def cmd_mcp(args: str, config: dict) -> str | None:
    """Handle /mcp [list|reload|add|remove]."""
    try:
        from mcp.tools import initialize_mcp, reload_mcp
        from mcp.manager import get_mcp_manager
        from mcp.config import add_server_to_user_config, remove_server_from_user_config
    except ImportError:
        from bouzecode.ui.ansi import warn
        warn("MCP package not available.")
        return None

    parts = args.strip().split(None, 1)
    sub = parts[0] if parts else "list"
    rest = parts[1] if len(parts) > 1 else ""

    if sub == "list":
        # Ensure MCP is initialized
        initialize_mcp()
        mgr = get_mcp_manager()
        servers = mgr.list_servers()
        if not servers:
            from bouzecode.ui.ansi import info
            info("No MCP servers configured.")
            return None
        lines = [client.status_line() for client in servers]
        return "MCP servers:\n" + "\n".join(f"  {line}" for line in lines)

    elif sub == "reload":
        errors = reload_mcp()
        from bouzecode.ui.ansi import ok, warn as _warn
        ok("MCP servers reloaded.")
        for name, err in errors.items():
            if err:
                _warn(f"  {name}: {err}")
        return None

    elif sub == "add":
        # Expected: /mcp add <name> <json_config>
        add_parts = rest.split(None, 1)
        if len(add_parts) < 2:
            from bouzecode.ui.ansi import err
            err("Usage: /mcp add <name> <json_config>")
            return None
        name = add_parts[0]
        try:
            raw = json.loads(add_parts[1])
        except json.JSONDecodeError as e:
            from bouzecode.ui.ansi import err
            err(f"Invalid JSON: {e}")
            return None
        add_server_to_user_config(name, raw)
        reload_mcp()
        from bouzecode.ui.ansi import ok
        ok(f"MCP server '{name}' added and connected.")
        return None

    elif sub == "remove":
        name = rest.strip()
        if not name:
            from bouzecode.ui.ansi import err
            err("Usage: /mcp remove <name>")
            return None
        removed = remove_server_from_user_config(name)
        if removed:
            reload_mcp()
            from bouzecode.ui.ansi import ok
            ok(f"MCP server '{name}' removed.")
        else:
            from bouzecode.ui.ansi import warn
            warn(f"MCP server '{name}' not found in user config.")
        return None

    else:
        from bouzecode.ui.ansi import err
        err(f"Unknown /mcp subcommand: {sub}. Use list|reload|add|remove.")
        return None
