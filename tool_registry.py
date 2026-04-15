# [desc] Central registry for tool plugins with registration, schema export, and dispatch. [/desc]
"""Tool plugin registry for bouzecode.

Provides a central registry for tool definitions, lookup, schema export,
and dispatch with output truncation.
"""
from __future__ import annotations

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
    """
    name: str
    schema: Dict[str, Any]
    func: Callable[[Dict[str, Any], Dict[str, Any]], str]
    read_only: bool = False
    concurrent_safe: bool = False


# --------------- internal state ---------------

_registry: Dict[str, ToolDef] = {}


# --------------- public API ---------------

def register_tool(tool_def: ToolDef) -> None:
    """Register a tool, overwriting any existing tool with the same name."""
    _registry[tool_def.name] = tool_def


def get_tool(name: str) -> Optional[ToolDef]:
    """Look up a tool by name. Returns None if not found."""
    return _registry.get(name)


def get_all_tools() -> List[ToolDef]:
    """Return all registered tools (insertion order)."""
    return list(_registry.values())


_SCHEDULING_PROPS = {
    "tool_call_alias": {
        "type": "string",
        "description": (
            "Optional alias for this tool call (e.g. 'w1', 'edit_a'). "
            "Other tools in the same turn can reference this alias in their "
            "depends_on array instead of the auto-generated tool_use ID."
        ),
    },
    "depends_on": {
        "type": "array",
        "items": {"type": "string"},
        "description": (
            "List of tool_call IDs or aliases that must complete before this tool runs. "
            "Use this to chain tools in a single turn without extra LLM round-trips. "
            "Example: Write a file then run it — the Bash call lists the Write call's ID."
        ),
    },
}


def get_tool_schemas() -> List[Dict[str, Any]]:
    """Return the schemas of all registered tools (for API tool parameter).

    Automatically injects the optional ``depends_on`` property into every
    tool's input_schema so the LLM can express dependency trees.
    """
    import copy
    schemas = []
    for t in _registry.values():
        s = copy.deepcopy(t.schema)
        props = s.get("input_schema", {}).get("properties")
        if props is not None and "depends_on" not in props:
            props.update(_SCHEDULING_PROPS)
        schemas.append(s)
    return schemas


def _coerce_params(params: Dict[str, Any], schema: Dict[str, Any]) -> None:
    """Coerce string values from the XML parser to their JSON-schema types."""
    import json as _json
    props = schema.get("input_schema", {}).get("properties", {})
    for key, value in list(params.items()):
        if key not in props or not isinstance(value, str):
            continue
        declared = props[key].get("type")
        if declared == "integer":
            try:
                params[key] = int(value)
            except (ValueError, TypeError):
                pass
        elif declared == "number":
            try:
                params[key] = float(value)
            except (ValueError, TypeError):
                pass
        elif declared == "boolean":
            params[key] = value.lower() not in ("false", "0", "no", "")
        elif declared in ("array", "object"):
            try:
                params[key] = _json.loads(value)
            except (ValueError, TypeError):
                pass


def execute_tool(
    name: str,
    params: Dict[str, Any],
    config: Dict[str, Any],
    max_output: int = 32000,
) -> str:
    """Dispatch a tool call by name.

    Args:
        name: tool name
        params: tool input parameters dict
        config: runtime configuration dict
        max_output: maximum allowed output length in characters

    Returns:
        Tool result string, possibly truncated.
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

    tool = get_tool(name)
    if tool is None:
        return f"Error: tool '{name}' not found."

    _coerce_params(params, tool.schema)

    try:
        result = tool.func(params, config)
    except Exception as e:
        return f"Error executing {name}: {e}"

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


def clear_registry() -> None:
    """Remove all registered tools. Intended for testing."""
    _registry.clear()
