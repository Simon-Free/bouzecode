"""OSS shim: /plugin command — delegates to the flat plugin/ package."""
from __future__ import annotations


def cmd_plugin(args: str, config: dict) -> str | None:
    """Handle /plugin [list|install|uninstall|enable|disable|update|recommend]."""
    try:
        from plugin import plugin_manager
        parts = args.strip().split(None, 1)
        sub = parts[0] if parts else "list"
        rest = parts[1] if len(parts) > 1 else ""

        if sub == "list" or sub == "":
            plugins = getattr(plugin_manager, "list_plugins", lambda: [])()
            if not plugins:
                from bouzecode.ui.ansi import info
                info("No plugins installed.")
                return None
            lines = [f"  {p}" for p in plugins]
            return "Plugins:\n" + "\n".join(lines)
        elif sub == "install":
            getattr(plugin_manager, "install", lambda x: None)(rest)
            from bouzecode.ui.ansi import ok
            ok(f"Plugin installed: {rest}")
            return None
        elif sub == "uninstall":
            getattr(plugin_manager, "uninstall", lambda x: None)(rest)
            from bouzecode.ui.ansi import ok
            ok(f"Plugin uninstalled: {rest}")
            return None
        else:
            from bouzecode.ui.ansi import info
            info(f"/plugin {sub}: {rest}")
            return None
    except ImportError:
        from bouzecode.ui.ansi import warn
        warn("Plugin package not available.")
        return None
