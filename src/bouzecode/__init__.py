"""Bouzecode package — new engine entry point.

Also provides backward-compatible re-exports so flat packages (repl.py,
commands/, tests/) that did `from bouzecode import X` keep working.
"""
from __future__ import annotations

VERSION = "1.1.1"


def main():
    from .ui.cli import main as _main
    return _main()


def __getattr__(name):
    # --- New engine exports ---
    if name == "COMMANDS":
        from bouzecode.backend.commands.dispatcher import COMMANDS
        return COMMANDS
    if name == "handle_slash":
        from bouzecode.backend.commands.dispatcher import handle_slash
        return handle_slash

    # --- Legacy backward-compat re-exports for flat packages ---
    _ANSI_NAMES = {"C", "clr", "info", "ok", "warn", "err"}
    if name in _ANSI_NAMES:
        import ui.ansi as _ansi  # flat package at repo root
        return getattr(_ansi, name)

    _CMD_MISC = {"cmd_init", "cmd_export", "cmd_copy", "cmd_diff"}
    if name in _CMD_MISC:
        import commands.misc as _misc  # flat package at repo root
        return getattr(_misc, name)

    if name == "cmd_status":
        from commands.diagnostics import cmd_status as _cs
        return _cs

    if name == "strip_unpaired_surrogates":
        def _strip(raw: str) -> str:
            recombined = raw.encode("utf-16", "surrogatepass").decode("utf-16", "replace")
            return recombined.encode("utf-8", "replace").decode("utf-8", "replace")
        return _strip

    raise AttributeError(f"module 'bouzecode' has no attribute {name!r}")
