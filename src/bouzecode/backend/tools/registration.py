# [desc] Registers built-in tool definitions and executes tools with permission checks. [/desc]
"""Tool registration: builtins, plan mode, and side-effect plugin imports."""
from typing import Callable, Optional

from ..core.tool_registry import ToolDef, register_tool
from ..core.tool_registry import execute_tool as _registry_execute

from .schemas import TOOL_SCHEMAS
from .ops.file_ops import _read, _write, _edit
from .ops.shell_search import _is_safe_bash, _bash, _glob, _grep
from .ops.web_ops import _webfetch, _websearch
from .ops.notebook_diagnostics import _notebook_edit, _get_diagnostics
from .interaction import _ask_user_question, _sleeptimer
from .ops.diff_ops import _get_diff
from ..context_manager.methodology import methodology_tool, snippet_tool


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

    # Plan check disabled — WritePlan is advisory, not enforced.

    return _registry_execute(name, inputs, cfg)


def _final_answer(answer: str, config: dict) -> str:
    """Explicit close signal (ends_turn=True): store and echo the final answer.
    On native models a one-call validator checks the Methodology todolist first
    and can REFUSE the close (loop continues via _final_answer_refused)."""
    if not answer.strip():
        config["_final_answer_refused"] = True
        return "Error: 'answer' is empty — provide the complete final answer."
    from ..agent.close_validator import validate_close
    accepted, feedback = validate_close(answer, config)
    if not accepted:
        config["_final_answer_refused"] = True
        return (f"CLÔTURE REFUSÉE par le validateur — il manque : {feedback}\n"
                "Termine ce qui manque (coche ta todolist) puis rappelle FinalAnswer.")
    config["_final_answer"] = answer
    state = config.get("_state")
    if state is not None:
        state.final_answer = answer
    return f"Session closing — final answer delivered:\n{answer}"


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
            func=lambda p, c: _glob(p["pattern"], p.get("path"), p.get("ignore_gitignore", True), p.get("include_patterns")),
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
                p.get("ignore_gitignore", True),
                p.get("include_patterns"),
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
            name="Methodology",
            schema=_schemas["Methodology"],
            func=lambda p, c: methodology_tool(p, c),
            read_only=False,
            concurrent_safe=False,
        ),
        ToolDef(
            name="FinalAnswer",
            schema=_schemas["FinalAnswer"],
            func=lambda p, c: _final_answer(p.get("answer", ""), c),
            read_only=True,
            concurrent_safe=False,
            ends_turn=True,
        ),
        ToolDef(
            name="Snippet",
            schema=_schemas["Snippet"],
            func=lambda p, c: snippet_tool(p, c),
            read_only=False,
            concurrent_safe=False,
        ),
        ToolDef(
            name="GetDiff",
            schema=_schemas["GetDiff"],
            func=lambda p, c: _get_diff(p.get("file_path")),
            read_only=True,
            concurrent_safe=True,
        ),
    ]
    for td in _tool_defs:
        register_tool(td)


_register_builtins()


# ── Project config tool ──────────────────────────────────────────────────────
from .ops.project_config import _load_project_config

_schemas_map = {s["name"]: s for s in TOOL_SCHEMAS}
register_tool(ToolDef(
    name="LoadProjectConfig",
    schema=_schemas_map["LoadProjectConfig"],
    func=lambda p, c: _load_project_config(p["path"]),
    read_only=False,
    concurrent_safe=False,
))


# ── Plan mode tools ──────────────────────────────────────────────────────────
from .plan_mode import _enter_plan_mode, _exit_plan_mode, _write_plan, _PLAN_MODE_SCHEMAS

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
from ..multi_agent import tools as _multiagent_tools  # noqa: F401
from ..multi_agent.tools import get_agent_manager as _get_agent_manager  # noqa: F401
from .skill import tools as _skill_tools  # noqa: F401
from .task import tools as _task_tools  # noqa: F401

from ..checkpoint.hooks import install_hooks as _install_checkpoint_hooks
_install_checkpoint_hooks()

from .grep_guard import install_grep_guard as _install_grep_guard
_install_grep_guard()

from .folder_desc import tools as _folder_desc_tools  # noqa: F401

# Memory tools from the flat memory/ package (registers MemorySave/Delete/Search/List)
import memory.tools as _memory_tools  # noqa: F401

# ── RunPythonTest tool ───────────────────────────────────────────────────────

from .ops.test_runner import run_python_test as _run_python_test

_schemas_map2 = {s["name"]: s for s in TOOL_SCHEMAS}
register_tool(ToolDef(
    name="RunPythonTest",
    schema=_schemas_map2["RunPythonTest"],
    func=lambda p, c: _run_python_test(
        targets=p.get("targets"),
        parallel=p.get("parallel", "auto"),
        marker=p.get("marker"),
        keyword=p.get("keyword"),
        timeout=p.get("timeout", 300),
        extra_args=p.get("extra_args"),
        no_sync=p.get("no_sync", False),
    ),
    read_only=True,
    concurrent_safe=True,
))

# ── Default enabled tools (whitelist) ─────────────────────────────────────────
# Only these tools are sent to the model. All others are disabled at import time.
# Re-enable at runtime via enable_tool() or config["extra_tools"].
from ..core.tool_registry import disable_tool, _registry

_DEFAULT_ENABLED = {
    "Read", "Write", "Edit", "Bash", "Glob", "Grep",
    "Methodology", "Snippet", "GetDiff", "WritePlan", "FinalAnswer",
    "AskUserQuestion", "Skill", "SkillList", "LoadProjectConfig", "TaskList",
    "MemorySave", "MemoryList",
}

for _tool_name in list(_registry.keys()):
    if _tool_name not in _DEFAULT_ENABLED:
        disable_tool(_tool_name)

# ── MCP tools (registered after disable loop → stay enabled) ─────────────────
try:
    from mcp.tools import initialize_mcp as _initialize_mcp
    _initialize_mcp()
except Exception:
    pass  # No MCP config or mcp package issue — non-fatal
