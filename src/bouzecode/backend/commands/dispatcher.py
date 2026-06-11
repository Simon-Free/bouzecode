# [desc] Registers slash commands and dispatches user input to the appropriate command handler. [/desc]
"""Slash command dispatcher: COMMANDS table, _CMD_META, handle_slash."""
from __future__ import annotations

from typing import Union

from bouzecode.ui.ansi import err
from .core import cmd_help, cmd_clear, cmd_model, cmd_config, cmd_exit, cmd_tools
from .core import cmd_verbose, cmd_thinking, cmd_permissions, cmd_cwd
from .session import cmd_save, cmd_where, cmd_load, cmd_resume
from .session.checkpoint_cmd import cmd_checkpoint
from .session.revert_cmd import cmd_revert
from .info import cmd_history, cmd_context, cmd_cost, cmd_timing, cmd_doctor
from .extensions import cmd_agents, cmd_skills, cmd_tasks
from .proactive import cmd_proactive
from .image_cmd import cmd_image
from .worker import cmd_worker
from .ssj import cmd_ssj
from .telegram_cmd import cmd_telegram
from .plan_cmd import cmd_plan
from .misc import cmd_compact, cmd_init, cmd_export, cmd_copy, cmd_diff
from .oss_shims import OSS_COMMANDS


cmd_rewind = cmd_checkpoint  # alias


COMMANDS = {
    "help":        cmd_help,
    "clear":       cmd_clear,
    "model":       cmd_model,
    "config":      cmd_config,
    "save":        cmd_save,
    "load":        cmd_load,
    "history":     cmd_history,
    "context":     cmd_context,
    "cost":        cmd_cost,
    "timing":      cmd_timing,
    "verbose":     cmd_verbose,
    "thinking":    cmd_thinking,
    "permissions": cmd_permissions,
    "cwd":         cmd_cwd,
    "skills":      cmd_skills,
    "agents":      cmd_agents,
    "tasks":       cmd_tasks,
    "task":        cmd_tasks,
    "checkpoint":  cmd_checkpoint,
    "rewind":      cmd_rewind,
    "revert":      cmd_revert,
    "plan":        cmd_plan,
    "compact":     cmd_compact,
    "init":        cmd_init,
    "export":      cmd_export,
    "copy":        cmd_copy,
    "diff":        cmd_diff,
    "doctor":      cmd_doctor,
    "exit":        cmd_exit,
    "quit":        cmd_exit,
    "resume":      cmd_resume,
    "where":       cmd_where,
    "tools":       cmd_tools,
    **OSS_COMMANDS,
}


_CMD_META: dict[str, tuple[str, list[str]]] = {
    "help":        ("Show help",                          []),
    "clear":       ("Clear conversation history",         []),
    "model":       ("Show / set model",                   []),
    "config":      ("Show / set config key=value",        []),
    "save":        ("Save session to file",               []),
    "load":        ("Load sessions (today / YYYY-MM-DD / file)", []),
    "history":     ("Show conversation history",          []),
    "context":     ("Show token-context usage",           []),
    "cost":        ("Show cost estimate",                 []),
    "verbose":     ("Toggle verbose output",              []),
    "thinking":    ("Toggle extended thinking",           []),
    "permissions": ("Set permission mode",                ["auto", "accept-all", "manual"]),
    "cwd":         ("Show / change working directory",    []),
    "skills":      ("List available skills",              []),
    "agents":      ("Show background agents",             []),
    "tasks":       ("Manage tasks",                       ["create", "delete", "get", "clear",
                                                           "todo", "in-progress", "done", "blocked"]),
    "task":        ("Manage tasks (alias)",               ["create", "delete", "get", "clear",
                                                           "todo", "in-progress", "done", "blocked"]),
    "checkpoint":  ("List / restore checkpoints",          ["clear"]),
    "rewind":      ("Rewind to checkpoint (alias)",        ["clear"]),
    "revert":      ("Revert all changes to last user input", []),
    "plan":        ("Enter/exit plan mode",                ["done", "status"]),
    "compact":     ("Compact conversation history",         []),
    "init":        ("Initialize CLAUDE.md template",        []),
    "export":      ("Export conversation to file",          []),
    "copy":        ("Copy last response to clipboard",      []),
    "diff":        ("Show diffs from recent Edit/Write",    []),
    "doctor":      ("Diagnose installation health",         []),
    "exit":        ("Exit bouz\u00e9code",                      []),
    "quit":        ("Exit (alias for /exit)",             []),
    "resume":      ("Resume last session",                []),
    "where":       ("Show session log file paths",        []),
    "tools":       ("List / enable / disable tools",      ["disable", "enable", "reset"]),
}


_REPL_SENTINELS = ("__voice__", "__image__", "__worker__",
                   "__ssj_cmd__", "__ssj_query__", "__ssj_debate__",
                   "__ssj_passthrough__", "__plan__")


def handle_slash(line: str, state, config) -> Union[bool, tuple]:
    """Handle /command [args]. Returns True if handled, tuple (skill, args) for skill match."""
    if not line.startswith("/"):
        return False
    parts = line[1:].split(None, 1)
    if not parts:
        return False
    cmd = parts[0].lower()
    args = parts[1] if len(parts) > 1 else ""
    handler = COMMANDS.get(cmd)
    if handler:
        result = handler(args, state, config)
        if isinstance(result, tuple) and result[0] in _REPL_SENTINELS:
            return result
        return True

    from bouzecode.backend.tools.skill import find_skill
    skill = find_skill(line)
    if skill:
        cmd_parts = line.strip().split(maxsplit=1)
        skill_args = cmd_parts[1] if len(cmd_parts) > 1 else ""
        return (skill, skill_args)

    err(f"Unknown command: /{cmd}  (type /help for commands)")
    return True
