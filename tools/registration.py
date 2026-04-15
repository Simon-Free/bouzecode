# [desc] Registers built-in tool definitions and executes tools with permission checks. [/desc]
"""Tool registration: builtins, plan mode, and side-effect plugin imports."""
from typing import Callable, Optional

from tool_registry import ToolDef, register_tool
from tool_registry import execute_tool as _registry_execute

from tools.schemas import TOOL_SCHEMAS
from tools.ops.file_ops import _read, _write, _edit
from tools.ops.shell_search import _is_safe_bash, _bash, _glob, _grep
from tools.ops.web_ops import _webfetch, _websearch
from tools.ops.notebook_diagnostics import _notebook_edit, _get_diagnostics
from tools.interaction import _ask_user_question, _sleeptimer
from context_gc import process_gc_call


def execute_tool(
    name: str,
    inputs: dict,
    permission_mode: str = "auto",
    ask_permission: Optional[Callable[[str], bool]] = None,
    config: dict = None,
) -> str:
    cfg = config or {}

    def _check(desc: str) -> bool:
        if permission_mode == "accept-all":
            return True
        if ask_permission:
            return ask_permission(desc)
        return True

    if name == "Write":
        if not _check(f"Write to {inputs['file_path']}"):
            return "Denied: user rejected write operation"
    elif name == "Edit":
        if not _check(f"Edit {inputs['file_path']}"):
            return "Denied: user rejected edit operation"
    elif name == "Bash":
        cmd = inputs["command"]
        if permission_mode != "accept-all" and not _is_safe_bash(cmd):
            if not _check(f"Bash: {cmd}"):
                return "Denied: user rejected bash command"
    elif name == "NotebookEdit":
        if not _check(f"Edit notebook {inputs['notebook_path']}"):
            return "Denied: user rejected notebook edit operation"

    return _registry_execute(name, inputs, cfg)


def _register_builtins() -> None:
    _schemas = {s["name"]: s for s in TOOL_SCHEMAS}

    _tool_defs = [
        ToolDef(
            name="Read",
            schema=_schemas["Read"],
            func=lambda p, c: _read(**p),
            read_only=True,
            concurrent_safe=True,
        ),
        ToolDef(
            name="Write",
            schema=_schemas["Write"],
            func=lambda p, c: _write(**p),
            read_only=False,
            concurrent_safe=False,
        ),
        ToolDef(
            name="Edit",
            schema=_schemas["Edit"],
            func=lambda p, c: _edit(**p),
            read_only=False,
            concurrent_safe=False,
        ),
        ToolDef(
            name="Bash",
            schema=_schemas["Bash"],
            func=lambda p, c: _bash(p["command"], p.get("timeout", 30)),
            read_only=False,
            concurrent_safe=False,
        ),
        ToolDef(
            name="Glob",
            schema=_schemas["Glob"],
            func=lambda p, c: _glob(p["pattern"], p.get("path")),
            read_only=True,
            concurrent_safe=True,
        ),
        ToolDef(
            name="Grep",
            schema=_schemas["Grep"],
            func=lambda p, c: _grep(
                p["pattern"], p.get("path"), p.get("glob"),
                p.get("output_mode", "content"),
                p.get("case_insensitive", False),
                p.get("context", 0),
            ),
            read_only=True,
            concurrent_safe=True,
        ),
        ToolDef(
            name="WebFetch",
            schema=_schemas["WebFetch"],
            func=lambda p, c: _webfetch(p["url"], p.get("prompt")),
            read_only=True,
            concurrent_safe=True,
        ),
        ToolDef(
            name="WebSearch",
            schema=_schemas["WebSearch"],
            func=lambda p, c: _websearch(p["query"]),
            read_only=True,
            concurrent_safe=True,
        ),
        ToolDef(
            name="NotebookEdit",
            schema=_schemas["NotebookEdit"],
            func=lambda p, c: _notebook_edit(
                p["notebook_path"],
                p["new_source"],
                p.get("cell_id"),
                p.get("cell_type"),
                p.get("edit_mode", "replace"),
            ),
            read_only=False,
            concurrent_safe=False,
        ),
        ToolDef(
            name="GetDiagnostics",
            schema=_schemas["GetDiagnostics"],
            func=lambda p, c: _get_diagnostics(
                p["file_path"],
                p.get("language"),
            ),
            read_only=True,
            concurrent_safe=True,
        ),
        ToolDef(
            name="AskUserQuestion",
            schema=_schemas["AskUserQuestion"],
            func=lambda p, c: _ask_user_question(
                p["question"],
                p.get("options"),
                p.get("allow_freetext", True),
                config=c,
            ),
            read_only=True,
            concurrent_safe=False,
        ),
        ToolDef(
            name="SleepTimer",
            schema=_schemas["SleepTimer"],
            func=lambda p, c: _sleeptimer(p["seconds"], c),
            read_only=False,
            concurrent_safe=True,
        ),
        ToolDef(
            name="ContextGC",
            schema=_schemas["ContextGC"],
            func=lambda p, c: process_gc_call(p, c),
            read_only=True,
            concurrent_safe=True,
        ),
    ]
    for td in _tool_defs:
        register_tool(td)


_register_builtins()


# ── Plan mode tools ──────────────────────────────────────────────────────────
from tools.plan_mode import _enter_plan_mode, _exit_plan_mode, _write_plan, _PLAN_MODE_SCHEMAS

register_tool(ToolDef(
    name="EnterPlanMode",
    schema=_PLAN_MODE_SCHEMAS[0],
    func=_enter_plan_mode,
    read_only=False,
    concurrent_safe=False,
))

register_tool(ToolDef(
    name="WritePlan",
    schema=_PLAN_MODE_SCHEMAS[1],
    func=_write_plan,
    read_only=False,
    concurrent_safe=False,
))

register_tool(ToolDef(
    name="ExitPlanMode",
    schema=_PLAN_MODE_SCHEMAS[2],
    func=_exit_plan_mode,
    read_only=False,
    concurrent_safe=False,
))


# ── Side-effect imports: register tools from other packages ──────────────────
import memory.tools as _memory_tools  # noqa: F401
import multi_agent.tools as _multiagent_tools  # noqa: F401
from multi_agent.tools import get_agent_manager as _get_agent_manager  # noqa: F401
import skill.tools as _skill_tools  # noqa: F401
import mcp.tools as _mcp_tools  # noqa: F401

try:
    from plugin.loader import register_plugin_tools as _reg_plugin_tools
    _reg_plugin_tools()
except Exception:
    pass

import task.tools as _task_tools  # noqa: F401

from checkpoint.hooks import install_hooks as _install_checkpoint_hooks
_install_checkpoint_hooks()

import folder_desc.tools as _folder_desc_tools  # noqa: F401
