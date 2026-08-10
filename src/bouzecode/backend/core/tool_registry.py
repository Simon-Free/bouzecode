# [desc] Central registry for tool plugins with thread-local overlays for concurrent conversations. [/desc]
"""Tool plugin registry for bouzecode.

Provides a central registry for tool definitions, lookup, schema export,
and dispatch with output truncation.  Supports thread-local overlays so
concurrent conversations in one process each get an isolated view.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional


@dataclass
class ToolDef:
    """Definition of a single tool plugin.

    Attributes:
        name: unique tool identifier
        schema: JSON-schema dict sent to the API (name, description, input_schema)
        func: callable(params: dict, config: dict) -> str
        read_only: True if the tool never mutates state
        concurrent_safe: True if safe to run in parallel with other tools
        ends_turn: True if a turn containing only this tool should NOT trigger a
            follow-up LLM cycle — the tool result is self-contained and the
            model has nothing meaningful to add afterwards.
        snippetable: True if this tool's result should be wrapped on the wire with
            snippet markers (see snippet_wire.py) so the model can freeze useful
            line ranges via Snippet(...).
        snippet_key: which identifier the model passes to Snippet — "tool_id"
            (default) or "file" (file_path-keyed).
    """
    name: str
    schema: Dict[str, Any]
    func: Callable[[Dict[str, Any], Dict[str, Any]], str]
    read_only: bool = False
    concurrent_safe: bool = False
    ends_turn: bool = False
    snippetable: bool = False
    snippet_key: Optional[str] = None


# --------------- framework vs work tools ---------------

# Framework tools are ALWAYS available to every agent, independent of any
# profile `tools` whitelist: they carry the methodology/discipline, skills,
# planning, diffing and final-answer machinery the harness relies on. A
# profile's `tools` list only ever whitelists the *work* tools (Read/Write/
# Edit/Bash/Glob/Grep/Agent/…); it can never strip these.
# AgentsMap/SymbolMap belong here for the same reason Skill/SkillList do: the
# code-navigation protocol that names them lives in the SHARED noyau
# (`context.get_readme_navigation_section`), which every agent receives whatever its
# profile. A profile whitelist that could strip them would ship a prompt prescribing
# tools the agent cannot call — the exact contradiction the conformity test forbids.
# Both are strictly read-only on source: their only write is the derived map file.
FRAMEWORK_ALWAYS_ON = frozenset({
    "Methodology", "Snippet", "FinalAnswer", "Skill", "SkillList",
    "TaskList", "GetDiff", "WritePlan", "LoadProjectConfig", "AskUserQuestion",
    "AgentsMap", "SymbolMap",
})


# --------------- internal state ---------------

_registry: Dict[str, ToolDef] = {}
_disabled: set = set()  # tool names currently disabled

# Thread-local overlay for conversations running in parallel
_local = threading.local()


def _has_overlay() -> bool:
    """Return True if the current thread has an active local overlay."""
    return getattr(_local, "active", False)


def _local_registry() -> Dict[str, ToolDef]:
    return getattr(_local, "registry", {})


def _local_disabled() -> set:
    return getattr(_local, "disabled", set())


# --------------- overlay lifecycle ---------------

def push_local_overlay() -> None:
    """Activate a thread-local overlay.

    While active, register/disable/enable operate on the local state,
    and lookups check local first then fall through to global.

    Le registre GLOBAL est peuplé AVANT d'activer l'overlay, et ce n'est pas une commodité.
    `registration` enregistre les 35 outils intégrés par EFFET DE BORD à l'import ; si cet
    import a lieu overlay actif, ils tombent dans `_local.registry` et `pop_local_overlay()`
    les JETTE. Le module restant dans `sys.modules`, plus aucun ré-import ne repeuple le
    global : il garde définitivement les seuls outils enregistrés hors overlay. Mesuré le
    2026-07-29 — 7 outils sur 42, `get_tool("Read")` rendant `None` pour toute la vie du
    processus, et `scope_guard` dénonçant `Read, Glob, Grep` comme outils d'écriture.
    """
    import bouzecode.backend.tools.registration  # noqa: F401 — peuple le registre GLOBAL
    _local.active = True
    _local.registry = {}
    _local.disabled = set()


def pop_local_overlay() -> None:
    """Deactivate the thread-local overlay, discarding local state."""
    _local.active = False
    _local.registry = {}
    _local.disabled = set()


# --------------- public API ---------------

def register_tool(tool_def: ToolDef) -> None:
    """Register a tool, overwriting any existing tool with the same name."""
    if _has_overlay():
        _local.registry[tool_def.name] = tool_def
    else:
        _registry[tool_def.name] = tool_def


def get_tool(name: str) -> Optional[ToolDef]:
    """Look up a tool by name. Returns None if not found."""
    if _has_overlay():
        local = _local_registry().get(name)
        if local is not None:
            return local
    return _registry.get(name)


def get_all_tools() -> List[ToolDef]:
    """Return all registered tools (insertion order)."""
    if _has_overlay():
        merged = dict(_registry)
        merged.update(_local_registry())
        return list(merged.values())
    return list(_registry.values())


# Scheduling properties injected into every tool schema
_SCHEDULING_PROPS: Dict[str, Any] = {
    "depends_on": {
        "type": "array",
        "items": {"type": "string"},
        "description": (
            "List of tool_call_alias values that must complete before this tool runs. "
            "Use to express execution order within a single batch."
        ),
    },
    "tool_call_alias": {
        "type": "string",
        "description": (
            "Optional short alias for this tool call (e.g. 'w1'). "
            "Other tools can reference it in their depends_on."
        ),
    },
}


def _coerce_params(params: Dict[str, Any], schema: Dict[str, Any]) -> None:
    """Best-effort type coercion of tool params to match declared schema types.

    Mutates *params* in place.  Currently handles:
    - string→int / string→float for numeric properties
    - string→bool for boolean properties
    - string→list for array properties (tries JSON parse)
    - int/float→string for string properties
    """
    props = schema.get("input_schema", {}).get("properties", {})
    for key, value in list(params.items()):
        prop_schema = props.get(key)
        if not prop_schema:
            continue
        declared_type = prop_schema.get("type")
        if declared_type == "integer" and isinstance(value, str):
            try:
                params[key] = int(value)
            except ValueError:
                raise ValueError(f"Parameter '{key}' expects integer, got '{value}'")
        elif declared_type == "number" and isinstance(value, str):
            try:
                params[key] = float(value)
            except ValueError:
                raise ValueError(f"Parameter '{key}' expects number, got '{value}'")
        elif declared_type == "boolean" and isinstance(value, str):
            if value.lower() in ("true", "1", "yes"):
                params[key] = True
            elif value.lower() in ("false", "0", "no"):
                params[key] = False
            else:
                raise ValueError(f"Parameter '{key}' expects boolean, got '{value}'")
        elif declared_type == "array" and isinstance(value, str):
            import json
            try:
                parsed = json.loads(value)
                if isinstance(parsed, list):
                    params[key] = parsed
            except json.JSONDecodeError:
                pass
        elif declared_type == "string" and isinstance(value, (int, float)):
            params[key] = str(value)


def get_tool_schemas() -> List[Dict[str, Any]]:
    """Return the schemas of all registered tools (for API tool parameter).

    Automatically injects the optional ``depends_on`` property into every
    tool's input_schema so the LLM can express dependency trees.
    """
    import copy

    if _has_overlay():
        disabled = _local_disabled()
        merged = dict(_registry)
        merged.update(_local_registry())
        tools_iter = merged.values()
    else:
        disabled = _disabled
        tools_iter = _registry.values()

    schemas = []
    for t in tools_iter:
        if t.name in disabled:
            continue
        s = copy.deepcopy(t.schema)
        props = s.get("input_schema", {}).get("properties")
        if props is not None and "depends_on" not in props:
            props.update(_SCHEDULING_PROPS)
        schemas.append(s)
    return schemas


def execute_tool(
    name: str,
    params: Dict[str, Any],
    config: Dict[str, Any],
    max_output: int = 120000,
) -> str:
    """Dispatch a tool call by name.

    Args:
        name: tool name
        params: tool input parameters dict
        config: runtime configuration dict
        max_output: maximum allowed output length in characters. Ignored for
            snippetable tools (see below).

    Returns:
        Tool result string, possibly truncated. Snippetable tools are never
        truncated here — the snippet wire owns large results.
    """
    # Strip scheduling hints — not actual tool parameters
    params.pop("depends_on", None)
    params.pop("tool_call_alias", None)

    if name == "_InvalidToolName":
        corrupted = params.get("_corrupted_name", "<unknown>")
        return (
            f"ERROR: the tool name {corrupted!r} is malformed (must match [a-zA-Z0-9_-]+). "
            "This usually means an upstream proxy mangled your tool call. "
            "Please re-emit the same tool call with a clean name "
            "(e.g. 'Write', 'Edit', 'Glob') and identical input parameters; do not retry verbatim."
        )

    if name == "_XmlParseError":
        diagnostic = params.get("_error", "unknown XML parse error")
        source = params.get("_source", "")
        return (
            f"ERROR parsing your tool call XML: {diagnostic}\n"
            f"Offending source: {source!r}\n"
            "Please re-emit the tool call with correctly-formed XML: "
            "<tool_use name=\"...\" id=\"...\"><param name=\"...\">value</param></tool_use>. "
            "Wrap values containing <, > or & in <![CDATA[...]]>."
        )

    # Check disabled — use overlay if active, else global
    if _has_overlay():
        disabled = _local_disabled()
    else:
        disabled = _disabled

    # A refusal must be TERMINAL: the agent cannot enable a tool itself, so the old
    # "Use /tools enable X" (a REPL command it cannot emit) bought 44 measured
    # relaunches of the very same refused call. The replacement names substitutes
    # taken from the registry this agent really has.
    from .tool_mentions import unavailable_tool_message

    if name in disabled:
        return unavailable_tool_message(name, available_tool_names())

    tool = get_tool(name)
    if tool is None:
        return unavailable_tool_message(name, available_tool_names(), missing=True)

    valid_params = set((tool.schema.get("input_schema", {}).get("properties") or {}).keys())
    if valid_params:
        unknown = [k for k in params if k not in valid_params]
        if unknown:
            return (
                f"Error: unknown parameter(s) for {name}: {', '.join(unknown)}. "
                f"Valid parameters: {', '.join(sorted(valid_params))}."
            )

    # Guard against required params that arrived empty/blank. This is the
    # classic symptom of a serialization mishap (e.g. a param body truncated
    # because the model emitted raw quotes instead of wrapping the value in
    # CDATA): the param key exists but its value is "" or whitespace. Executing
    # anyway (e.g. Bash with command="") silently runs a no-op that lists the
    # cwd — a plausible-looking result that traps the model in a retry loop.
    # Refuse to execute and return an explicit, self-correcting message.
    required = (tool.schema.get("input_schema", {}) or {}).get("required", []) or []
    blank_required = [
        r for r in required
        if r not in params
        or (isinstance(params[r], str) and not params[r].strip())
    ]
    if blank_required:
        names = ", ".join(blank_required)
        return (
            f"Error: required parameter(s) for {name} arrived empty or missing: {names}. "
            "This usually means the value was truncated during serialization — most "
            "often because the value contained raw quotes (\") or angle brackets and "
            "was not wrapped in .... The call was NOT executed. "
            f"Please re-emit {name} with the parameter(s) filled and any value containing "
            "<, > or \" wrapped in ...."
        )

    try:
        _coerce_params(params, tool.schema)
    except ValueError as e:
        valid = ', '.join(sorted(valid_params)) if valid_params else "(none)"
        return f"Error: invalid parameter format for {name}: {e}. Valid parameters: {valid}."

    try:
        result = tool.func(params, config)
    except Exception as e:
        from bouzecode.backend.tools.interaction import PausedForInput, DeferredChecks
        from bouzecode.backend.tools.plan_mode import PlanRejected
        if isinstance(e, (PausedForInput, DeferredChecks, PlanRejected)):
            raise
        return f"Error executing {name}: {e}"

    # Snippetable tools are handled by the snippet wire (numbered lines,
    # destroyed-next-turn, model snippets the ranges it needs). Truncating here
    # would discard the MIDDLE of a large result before the model can snippet it
    # — exactly what broke get_br_content / get_br_generation_documentation on
    # >32 KB content (the variable-write rule lived in the truncated middle).
    if getattr(tool, "snippetable", False):
        return result

    if len(result) > max_output:
        first_half = max_output // 2
        last_quarter = max_output // 4
        truncated = len(result) - first_half - last_quarter
        result = (
            result[:first_half]
            + f"\n[... {truncated} chars truncated ...]\n"
            + result[-last_quarter:]
        )

    return result


def unregister_tool(name: str) -> None:
    """Remove a tool from the registry entirely."""
    if _has_overlay():
        _local_registry().pop(name, None)
        _local_disabled().discard(name)
    else:
        _registry.pop(name, None)
        _disabled.discard(name)


def disable_tool(name: str) -> None:
    """Disable a tool by name. Raises KeyError if tool not registered."""
    if _has_overlay():
        # In overlay mode, check both local and global for existence
        if name not in _local_registry() and name not in _registry:
            raise KeyError(f"Unknown tool: {name}")
        _local.disabled.add(name)
    else:
        if name not in _registry:
            raise KeyError(f"Unknown tool: {name}")
        _disabled.add(name)


def enable_tool(name: str) -> None:
    """Re-enable a previously disabled tool."""
    if _has_overlay():
        _local.disabled.discard(name)
    else:
        _disabled.discard(name)


def available_tool_names() -> List[str]:
    """Return the names this agent can actually call right now (registered AND enabled).

    This is the ground truth a refusal message must quote: anything else — a static
    list, a doc, a prompt — can drift out of the registry and prescribe a phantom.
    """
    return sorted(t.name for t in get_all_tools() if is_enabled(t.name))


def is_enabled(name: str) -> bool:
    """Return True if tool is not in the disabled set."""
    if _has_overlay():
        return name not in _local_disabled()
    return name not in _disabled


def list_disabled() -> List[str]:
    """Return sorted list of disabled tool names."""
    if _has_overlay():
        return sorted(_local_disabled())
    return sorted(_disabled)


def reset_disabled() -> None:
    """Re-enable all tools."""
    if _has_overlay():
        _local.disabled.clear()
    else:
        _disabled.clear()


def clear_registry() -> None:
    """Remove all registered tools. Intended for testing."""
    _registry.clear()
    _disabled.clear()
    if _has_overlay():
        _local.registry.clear()
        _local.disabled.clear()


def ends_turn(name: str) -> bool:
    """Return True if the named tool has ends_turn=True."""
    tool = get_tool(name)
    return tool.ends_turn if tool else False


def is_concurrent_safe(name: str) -> bool:
    """Return True if the named tool has concurrent_safe=True."""
    tool = get_tool(name)
    return tool.concurrent_safe if tool else False
