# [desc] Registers slash commands and dispatches user input to the appropriate command handler. [/desc]
"""Slash command dispatcher: COMMANDS table, _CMD_META, handle_slash."""
from __future__ import annotations

from typing import Union

from ui.ansi import err
from commands.basic import cmd_help, cmd_clear, cmd_model, cmd_config, cmd_exit
from commands.session import cmd_save, cmd_where
from commands.session_load import cmd_load, cmd_resume
from commands.info import cmd_history, cmd_context, cmd_cost, cmd_timing
from commands.settings import cmd_verbose, cmd_thinking, cmd_permissions, cmd_cwd
from commands.memory_cmd import cmd_memory, cmd_agents
from commands.skills_mcp import cmd_skills, cmd_mcp
from commands.plugin_cmd import cmd_plugin
from commands.tasks_cmd import cmd_tasks
from commands.proactive import cmd_proactive
from commands.cloudsave_cmd import cmd_cloudsave
from commands.voice_cmd import cmd_voice
from commands.image_cmd import cmd_image
from commands.brainstorm import cmd_brainstorm
from commands.worker import cmd_worker
from commands.ssj import cmd_ssj
from commands.telegram_cmd import cmd_telegram
from commands.video_cmd import cmd_video
from commands.checkpoint_cmd import cmd_checkpoint
from commands.plan_cmd import cmd_plan
from commands.misc import cmd_compact, cmd_init, cmd_export, cmd_copy, cmd_diff
from commands.diagnostics import cmd_status, cmd_doctor


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
    "memory":      cmd_memory,
    "agents":      cmd_agents,
    "mcp":         cmd_mcp,
    "plugin":      cmd_plugin,
    "tasks":       cmd_tasks,
    "task":        cmd_tasks,
    "proactive":   cmd_proactive,
    "cloudsave":   cmd_cloudsave,
    "voice":       cmd_voice,
    "image":       cmd_image,
    "img":         cmd_image,
    "brainstorm":  cmd_brainstorm,
    "worker":      cmd_worker,
    "ssj":         cmd_ssj,
    "telegram":    cmd_telegram,
    "video":       cmd_video,
    "checkpoint":  cmd_checkpoint,
    "rewind":      cmd_rewind,
    "plan":        cmd_plan,
    "compact":     cmd_compact,
    "init":        cmd_init,
    "export":      cmd_export,
    "copy":        cmd_copy,
    "diff":        cmd_diff,
    "status":      cmd_status,
    "doctor":      cmd_doctor,
    "exit":        cmd_exit,
    "quit":        cmd_exit,
    "resume":      cmd_resume,
    "where":       cmd_where,
}


_CMD_META: dict[str, tuple[str, list[str]]] = {
    "help":        ("Show help",                          []),
    "clear":       ("Clear conversation history",         []),
    "model":       ("Show / set model",                   []),
    "config":      ("Show / set config key=value",        []),
    "save":        ("Save session to file",               []),
    "load":        ("Load a saved session",               []),
    "history":     ("Show conversation history",          []),
    "context":     ("Show token-context usage",           []),
    "cost":        ("Show cost estimate",                 []),
    "verbose":     ("Toggle verbose output",              []),
    "thinking":    ("Toggle extended thinking",           []),
    "permissions": ("Set permission mode",                ["auto", "accept-all", "manual"]),
    "cwd":         ("Show / change working directory",    []),
    "skills":      ("List available skills",              []),
    "memory":      ("Search / list / consolidate memories", ["consolidate"]),
    "agents":      ("Show background agents",             []),
    "mcp":         ("Manage MCP servers",                 ["reload", "add", "remove"]),
    "plugin":      ("Manage plugins",                     ["install", "uninstall", "enable",
                                                           "disable", "disable-all", "update",
                                                           "recommend", "info"]),
    "tasks":       ("Manage tasks",                       ["create", "delete", "get", "clear",
                                                           "todo", "in-progress", "done", "blocked"]),
    "task":        ("Manage tasks (alias)",               ["create", "delete", "get", "clear",
                                                           "todo", "in-progress", "done", "blocked"]),
    "proactive":   ("Manage proactive background watcher", ["off"]),
    "cloudsave":   ("Cloud-sync sessions to GitHub Gist", ["setup", "auto", "list", "load", "push"]),
    "voice":       ("Voice input (record \u2192 STT)",         ["lang", "status", "device"]),
    "image":       ("Send clipboard image to model",      []),
    "img":         ("Send clipboard image (alias)",       []),
    "brainstorm":  ("Multi-persona AI debate + auto tasks", []),
    "worker":      ("Auto-implement pending tasks",       []),
    "ssj":         ("SSJ Developer Mode \u2014 power menu",    []),
    "telegram":    ("Telegram bot bridge",                ["stop", "status"]),
    "video":       ("AI video factory: story\u2192voice\u2192images\u2192mp4", ["status", "niches"]),
    "checkpoint":  ("List / restore checkpoints",          ["clear"]),
    "rewind":      ("Rewind to checkpoint (alias)",        ["clear"]),
    "plan":        ("Enter/exit plan mode",                ["done", "status"]),
    "compact":     ("Compact conversation history",         []),
    "init":        ("Initialize CLAUDE.md template",        []),
    "export":      ("Export conversation to file",          []),
    "copy":        ("Copy last response to clipboard",      []),
    "diff":        ("Show diffs from recent Edit/Write",    []),
    "status":      ("Show session status and model info",   []),
    "doctor":      ("Diagnose installation health",         []),
    "exit":        ("Exit bouz\u00e9code",                      []),
    "quit":        ("Exit (alias for /exit)",             []),
    "resume":      ("Resume last session",                []),
    "where":       ("Show session log file paths",        []),
}


_REPL_SENTINELS = ("__voice__", "__image__", "__brainstorm__", "__worker__",
                   "__ssj_cmd__", "__ssj_query__", "__ssj_debate__",
                   "__ssj_passthrough__", "__ssj_promote_worker__", "__plan__")


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

    from skill import find_skill
    skill = find_skill(line)
    if skill:
        cmd_parts = line.strip().split(maxsplit=1)
        skill_args = cmd_parts[1] if len(cmd_parts) > 1 else ""
        return (skill, skill_args)

    err(f"Unknown command: /{cmd}  (type /help for commands)")
    return True
