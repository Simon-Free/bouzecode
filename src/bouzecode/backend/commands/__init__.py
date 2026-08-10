# [desc] Package init that re-exports slash command dispatcher, REPL setup, and utility functions. [/desc]
"""Slash commands package — dispatcher, REPL setup, and per-command modules."""
from .dispatcher import COMMANDS, _CMD_META, handle_slash
from .readline_setup import setup_readline
from .core import ask_permission_interactive
from .session import save_latest, save_progressive, _build_session_data
from .proactive import _proactive_watcher_loop
from .telegram_cmd import _tg_send
from .extensions import _print_background_notifications

__all__ = [
    "COMMANDS", "_CMD_META", "handle_slash", "setup_readline",
    "ask_permission_interactive",
    "save_latest", "save_progressive", "_build_session_data",
    "_proactive_watcher_loop",
    "_tg_send",
    "_print_background_notifications",
]
