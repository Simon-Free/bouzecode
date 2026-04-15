# [desc] Package init that re-exports slash command dispatcher, REPL setup, and utility functions. [/desc]
"""Slash commands package — dispatcher, REPL setup, and per-command modules."""
from commands.dispatcher import COMMANDS, _CMD_META, handle_slash
from commands.readline_setup import setup_readline
from commands.basic import ask_permission_interactive
from commands.session import save_latest, save_progressive, _build_session_data
from commands.proactive import _proactive_watcher_loop
from commands.telegram_cmd import _tg_send
from commands.memory_cmd import _print_background_notifications

__all__ = [
    "COMMANDS", "_CMD_META", "handle_slash", "setup_readline",
    "ask_permission_interactive",
    "save_latest", "save_progressive", "_build_session_data",
    "_proactive_watcher_loop",
    "_tg_send",
    "_print_background_notifications",
]
