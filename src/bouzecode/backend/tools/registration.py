# [desc] Registers built-in tool definitions and executes tools with permission checks. [/desc]
"""Tool registration: builtins, plan mode, and side-effect plugin imports."""
from typing import Callable, Optional

from ..core.tool_registry import ToolDef, register_tool
from ..core.tool_registry import execute_tool as _registry_execute

from .schemas import TOOL_SCHEMAS
from .ops.file_ops import _read, _write, _edit
from .ops.shell_search import _is_safe_bash, _bash, bash_handler, _glob, _grep
from .ops.bash_bg import bash_output
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

    if name == "Read":
        # Snippet speaks 1-indexed inclusive `ranges`, Read speaks 0-indexed
        # offset+limit; the model mixes them. Convert what is exact arithmetic,
        # refuse what would need a choice. Runs BEFORE the registry's
        # unknown-parameter guard, which is what turned these into lost turns.
        from .ops.read_params import normalize_read_params
        error, note = normalize_read_params(inputs)
        if error:
            return error
        result = _registry_execute(name, inputs, cfg)
        if note and not result.startswith(("Error:", "__BOUZE_IMAGE__")):
            return f"{result}\n{note}"
        return result

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


def _coerce_recap(recap: object) -> object:
    """Certains modèles (Opus inclus) sérialisent l'objet `recap` en CHAÎNE JSON au lieu de
    passer un objet. On le reparse en dict — sinon un récap POURTANT complet est lu comme
    « tous les champs manquants » par le gate (refus en boucle), puis jeté à la persistance
    (`state.recap` reste None car non-dict) → tous les GET /recap sortent vides."""
    if isinstance(recap, str):
        import json
        try:
            parsed = json.loads(recap)
        except (ValueError, TypeError):
            return recap
        if isinstance(parsed, dict):
            return parsed
    return recap


def _final_answer(answer: str, config: dict, recap: object = None) -> str:
    """Explicit close signal (ends_turn=True): store and echo the final answer.
    On native models a one-call validator checks the Methodology todolist first
    and can REFUSE the close (loop continues via _final_answer_refused). When the
    profile sets require_recap the same gate also enforces a complete `recap`
    object (symptoms/explanation/tests/changes) before accepting the close."""
    if not answer.strip():
        config["_final_answer_refused"] = True
        return "Error: 'answer' is empty — provide the complete final answer."
    recap = _coerce_recap(recap)   # tolère un recap sérialisé en chaîne JSON (cf. _coerce_recap)
    from ..agent.close_validator import validate_close
    accepted, feedback = validate_close(answer, config, recap)
    if not accepted:
        config["_final_answer_refused"] = True
        return (f"CLÔTURE REFUSÉE par le validateur — il manque : {feedback}\n"
                "Termine ce qui manque (coche ta todolist) puis rappelle FinalAnswer.")
    config["_final_answer"] = answer
    state = config.get("_state")
    if state is not None:
        state.final_answer = answer
        # Récap persisté UNIQUEMENT pour les runs de LIVRAISON (work). Un validateur partage le
        # prompt du codeur et remplit parfois un `recap`, mais il rend un VERDICT : son « récap »
        # ne doit ni afficher de pastille ni polluer la vue consolidée du manager.
        import os
        if os.environ.get("BOUZECODE_RUN_KIND", "work") == "work":
            if isinstance(recap, dict):
                state.recap = recap
            if config.get("_recap_missing"):
                state.recap_missing = True
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
            func=lambda p, c: bash_handler(p, c),
            read_only=False,
            concurrent_safe=False,
        ),
        ToolDef(
            name="BashOutput",
            schema=_schemas["BashOutput"],
            func=lambda p, c: bash_output(p["bash_id"], p.get("kill", False)),
            read_only=True,
            concurrent_safe=True,
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
            # NOT concurrent_safe: firing several WebSearch in parallel from one
            # batch hits DuckDuckGo from the same (proxy) IP simultaneously and
            # trips its anti-bot "anomaly" page (0 results). Serialising lets the
            # module-level throttle in _websearch space the requests out.
            concurrent_safe=False,
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
            func=lambda p, c: _final_answer(p.get("answer", ""), c, p.get("recap")),
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

from ..context_manager.stale_hooks import install_stale_hooks as _install_stale_hooks
_install_stale_hooks()

from .folder_desc import tools as _folder_desc_tools  # noqa: F401

# Memory tools from the flat memory/ package (MemorySave/Delete/Search/List).
import memory.tools as _memory_tools  # noqa: F401

# Code-navigation maps. Registered BEFORE the whitelist pass below; they survive it
# through FRAMEWORK_ALWAYS_ON, because the noyau's navigation protocol names them to
# every agent (see tool_registry.FRAMEWORK_ALWAYS_ON).
from .agents_map import tools as _agents_map_tools  # noqa: F401

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

# ── AddProject tool (web_v2 project registry) ────────────────────────────────
# Registers a project into ~/.bouzecode/web_v2/projects.json so the model can
# add a project the same way the manual UI form does. Side-effect import.
from .projects_tool import tools as _projects_tool  # noqa: F401

# ── Plugin tools (pip packages from a package index) ────────────────────────
# Enabled plugins register their TOOL_DEFS here. Like other optional tools they
# are then gated by the whitelist below and re-enabled per-session via the
# agent profile's `requires_plugins` / `tools`.
from ..plugin.loader import register_plugin_tools as _register_plugin_tools
from ..plugin.loader import register_plugin_hooks as _register_plugin_hooks

# Skip plugin loading when BOUZECODE_NO_PLUGINS is set (CI/tests without
# package-index access, or when a plugin's native deps are broken in the env).
import os as _os

_plugin_count = 0 if _os.environ.get("BOUZECODE_NO_PLUGINS") else _register_plugin_tools()
if _plugin_count:
    print(f"[plugin] registered {_plugin_count} tool(s) from installed plugins")
# Plugins also contribute named hooks (HOOK_DEFS) into the pipeline catalog, but
# their registration is DEFERRED (loaded lazily by the pipeline catalog on first
# lookup, at agent startup). Calling it here — during `tools/__init__` import —
# pulls in `agent.hooks.pipeline` → `agent.__init__` → `loop` → `dag` →
# `..tools` while `tools` is still initialising, a circular import that crashes
# the agent subprocess. See pipeline._ensure_builtin.
_ = _register_plugin_hooks  # kept importable; invoked lazily from the pipeline

# ── Default enabled tools (whitelist) ─────────────────────────────────────────
# Only these tools are sent to the model. All others are disabled at import time.
# Re-enable at runtime via enable_tool() or config["extra_tools"].
from ..core.tool_registry import disable_tool, _registry, FRAMEWORK_ALWAYS_ON

# Work tools enabled by default for a plain agent (no profile whitelist).
# BashOutput pairs with Bash(background=true): without it an agent that launches a
# background process (e.g. a dev server) is blind to its stdout — it cannot read the
# boot output/port and ends up killing & restarting servers to compensate.
# RunPythonTest is prescribed by the `default` prose ("Lance-les via RunPythonTest")
# and by the Bash schema itself; leaving it disabled made the harness forbid what it
# prescribes — 94 measured refusals for a tool the prompt named in 29 % of sessions.
# MemorySave/MemoryList come from the flat memory/ package and are part of the
# public build's baseline: without them here the whitelist pass below would
# disable the tools that `import memory.tools` has just registered.
_DEFAULT_WORK_TOOLS = {"Read", "Write", "Edit", "Bash", "Glob", "Grep", "BashOutput",
                       "RunPythonTest", "AddProject", "WebFetch", "WebSearch",
                       "MemorySave", "MemoryList"}
# Sent to the model by default = framework (always-on) + default work tools.
_DEFAULT_ENABLED = set(FRAMEWORK_ALWAYS_ON) | _DEFAULT_WORK_TOOLS

for _tool_name in list(_registry.keys()):
    if _tool_name not in _DEFAULT_ENABLED:
        disable_tool(_tool_name)


def enabled_tools_for_profile(profile_name: str) -> set:
    """Return the tool names a `--profile <profile_name>` agent can call.

    Single source of truth for the profile whitelist, shared by `apply_profile_tools`
    (which enforces it on the live registry) and by the prompt/registry conformity
    test (which checks that nothing in that agent's prompt names a tool outside it).
    A profile with an empty `tools:` list means "no restriction" — whatever the
    registry currently has enabled, including tools switched on after the import-time
    whitelist (chrome-devtools bootstrap)."""
    from ..core.tool_registry import is_enabled
    from ..profiles import resolve_agent_profile

    profile = resolve_agent_profile(profile_name)
    declared = set(profile.tools) if profile and profile.tools else None
    if declared is None:
        return {name for name in _registry if is_enabled(name)}
    return {name for name in _registry if name in FRAMEWORK_ALWAYS_ON or name in declared}

# ── chrome-devtools MCP (opt-in via --enable-chrome-devtools) ─────────────────
# Registered AFTER the whitelist so its enable_tool() calls survive the global
# disable pass above. No-op unless BOUZECODE_ENABLE_CHROME_DEVTOOLS=1.
from ..chrome_devtools.launcher import register_chrome_devtools_tools as _register_cdt
from ..chrome_devtools.launcher import register_bootstrap_tools as _register_cdt_bootstrap
# Always-on Enable/DisableChromeDevtools bootstrap tools (lazy activation on demand),
# registered after the whitelist so their enable_tool() calls survive the disable pass.
_register_cdt_bootstrap()
try:
    _register_cdt()
except Exception as _cdt_err:  # noqa: BLE001
    print(f"[chrome-devtools] registration skipped: {_cdt_err}")

# ── MCP tools from the flat mcp/ package ─────────────────────────────────────
# Registered after the whitelist pass so they stay enabled. Non-fatal when no
# MCP server is configured.
from mcp.tools import initialize_mcp as _initialize_mcp
_initialize_mcp()
