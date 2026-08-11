# [desc] The two /doctor checks the README promises: ripgrep availability and tool-registry health. [/desc]
"""Health checks that /doctor renders, as pure functions.

Each returns `(level, message)` with level in {"pass", "warn", "fail"} so the
check can be asserted directly in a test instead of by scraping printed output.

Why these two: `rg` is what makes Grep/Glob usable on a real repository (the
fallback walks the tree in Python), and the tool registry IS the agent's whole
surface — an empty or unregistered registry means every turn fails.
"""
from __future__ import annotations

import subprocess


def ripgrep_status() -> tuple[str, str]:
    """Is `rg` on PATH, and which version.

    A missing rg is a WARN, not a FAIL: Grep/Glob keep working through the
    Python fallback, only far slower on a large tree."""
    try:
        result = subprocess.run(
            ["rg", "--version"], capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return "warn", (
            "ripgrep (rg): not found - Grep/Glob fall back to a slow Python walk. "
            "Install: winget install BurntSushi.ripgrep.MSVC"
        )
    if result.returncode != 0:
        return "warn", "ripgrep (rg): found but not working (`rg --version` failed)"
    first_line = result.stdout.strip().splitlines()[0] if result.stdout.strip() else "rg"
    return "pass", f"ripgrep: {first_line}"


# Tools without which the agent cannot do anything at all: read, act, and the
# two framework tools that carry its working memory and its close signal.
ESSENTIAL_TOOLS = ("Read", "Bash", "Methodology", "FinalAnswer")


def tool_registry_status() -> tuple[str, str]:
    """Is the tool registry populated, and are the essential tools enabled."""
    from ...core.tool_registry import get_tool_schemas, is_enabled, _registry

    registered = len(_registry)
    if registered == 0:
        return "fail", "Tool registry: EMPTY - no tool is registered, every turn will fail"
    offered = {schema["name"] for schema in get_tool_schemas()}
    missing = [name for name in ESSENTIAL_TOOLS
               if name in _registry and not is_enabled(name)]
    unregistered = [name for name in ESSENTIAL_TOOLS if name not in _registry]
    if unregistered:
        return "fail", (
            f"Tool registry: {registered} registered, but "
            f"{', '.join(unregistered)} missing"
        )
    if missing:
        return "warn", (
            f"Tool registry: {registered} registered / {len(offered)} offered, "
            f"disabled essentials: {', '.join(missing)}"
        )
    return "pass", f"Tool registry: {registered} registered / {len(offered)} offered to the model"
