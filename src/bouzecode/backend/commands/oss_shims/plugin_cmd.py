"""OSS shim: /plugin command — delegates to the flat plugin/ package."""
from __future__ import annotations


def cmd_plugin(args: str, config: dict) -> str | None:
    """Handle /plugin [list|install|uninstall|enable|disable|update|recommend]."""
    try:
        from plugin import list_plugins, install_plugin, uninstall_plugin
        from plugin import enable_plugin, disable_plugin, register_plugin_tools

        parts = args.strip().split(None, 1)
        sub = parts[0] if parts else "list"
        rest = parts[1] if len(parts) > 1 else ""

        if sub in ("list", ""):
            plugins = list_plugins()
            if not plugins:
                from bouzecode.ui.ansi import info
                info("No plugins installed.")
                return None
            lines = []
            for p in plugins:
                status = "enabled" if p.enabled else "disabled"
                lines.append(f"  {p.name} [{status}]")
            return "Plugins:\n" + "\n".join(lines)
        elif sub == "install":
            install_plugin(rest.strip())
            from bouzecode.ui.ansi import ok
            ok(f"Plugin installed: {rest.strip()}")
            return None
        elif sub == "uninstall":
            uninstall_plugin(rest.strip())
            from bouzecode.ui.ansi import ok
            ok(f"Plugin uninstalled: {rest.strip()}")
            return None
        elif sub == "enable":
            enable_plugin(rest.strip())
            from bouzecode.ui.ansi import ok
            ok(f"Plugin enabled: {rest.strip()}")
            return None
        elif sub == "disable":
            disable_plugin(rest.strip())
            from bouzecode.ui.ansi import ok
            ok(f"Plugin disabled: {rest.strip()}")
            return None
        elif sub == "load":
            count = register_plugin_tools()
            from bouzecode.ui.ansi import ok
            ok(f"Loaded {count} tool(s) from plugins.")
            return None
        else:
            from bouzecode.ui.ansi import info
            info(f"/plugin {sub}: not recognized. Use list|install|uninstall|enable|disable|load.")
            return None
    except ImportError:
        from bouzecode.ui.ansi import warn
        warn("Plugin package not available.")
        return None
