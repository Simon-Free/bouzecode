# [desc] In-process hook pipeline: named-hook catalog (builtin + plugin) + per-process event registry (register/fire/reset). [/desc]
"""Hook pipeline for the agent loop.

Two registries, mirroring the tool system:

* the **named-hook catalog** (`_NAMED`, name -> :class:`HookDef`) is populated by
  bouzecode builtins and by plugins that export ``HOOK_DEFS`` — exactly like
  ``TOOL_DEFS``. A profile references a hook by name in its ``hooks: [...]`` list.
* the **event registry** (`_HOOKS`, event -> [fn]) holds the hooks wired for THIS
  process (per-agent state). `apply_profile_hooks` resolves the profile's names
  against the catalog and `register_hook`s them; `loop.run()` `fire`s events.

The core (loop.py) only ever `fire`s events; all orchestration lives in the hook
functions (builtin or plugin) + the persisted ticket state.
"""
from __future__ import annotations

import sys
import traceback
from dataclasses import dataclass
from typing import Callable


@dataclass
class HookDef:
    """A named hook contributed by bouzecode or a plugin (mirror of ToolDef).

    ``func`` is called as ``func(ctx: HookContext) -> None`` when ``event`` fires.
    """
    name: str
    event: str
    func: Callable


# ── named-hook catalog (builtin + plugin) ─────────────────────────────────────

_NAMED: dict[str, HookDef] = {}
_builtin_loaded = False


def register_named_hook(hook: HookDef) -> None:
    """Register a named hook into the shared catalog (builtin or plugin)."""
    _NAMED[hook.name] = hook


def _ensure_builtin() -> None:
    """Populate the catalog once: bouzecode builtins + plugin HOOK_DEFS.

    Plugin registration is DEFERRED here (not at `tools/__init__` import) to avoid
    a circular import (tools→registration→plugin.loader→agent.loop→tools). This
    runs on first catalog lookup — at agent startup, after `tools` is fully
    initialised — so importing the plugin loader is safe."""
    global _builtin_loaded
    if _builtin_loaded:
        return
    _builtin_loaded = True
    from . import completion  # noqa: F401 — module registers its HOOK_DEFS below
    for hook in getattr(completion, "HOOK_DEFS", []):
        _NAMED.setdefault(hook.name, hook)
    import os
    if not os.environ.get("BOUZECODE_NO_PLUGINS"):
        try:
            from ...plugin.loader import register_plugin_hooks
            register_plugin_hooks()
        except Exception:  # noqa: BLE001 — plugin issues must not break the catalog
            print("[hooks] plugin hook registration failed:", file=sys.stderr)
            traceback.print_exc()


def get_named_hook(name: str) -> HookDef | None:
    _ensure_builtin()
    return _NAMED.get(name)


def all_named_hooks() -> dict[str, HookDef]:
    _ensure_builtin()
    return dict(_NAMED)


def reset_named() -> None:
    """Clear the catalog (tests). Builtins reload lazily on next lookup."""
    global _builtin_loaded
    _NAMED.clear()
    _builtin_loaded = False


# ── per-process event registry ────────────────────────────────────────────────

_HOOKS: dict[str, list[Callable]] = {}


def register_hook(event: str, fn: Callable) -> None:
    """Wire ``fn`` to ``event`` for this process."""
    _HOOKS.setdefault(event, []).append(fn)


def register_named(name: str) -> bool:
    """Resolve ``name`` in the catalog and wire it to its event. False if unknown."""
    hook = get_named_hook(name)
    if hook is None:
        return False
    register_hook(hook.event, hook.func)
    return True


def registered_events() -> dict[str, list[Callable]]:
    return {event: list(fns) for event, fns in _HOOKS.items()}


def fire(event: str, ctx) -> None:
    """Invoke every hook wired to ``event``. A failing hook is logged LOUDLY to
    stderr (never silently dropped) and never aborts the agent's graceful close."""
    for fn in list(_HOOKS.get(event, [])):
        try:
            fn(ctx)
        except Exception:  # noqa: BLE001 — a hook error must not crash the close
            print(f"[hooks] {event} hook {getattr(fn, '__name__', fn)!r} failed:",
                  file=sys.stderr)
            traceback.print_exc()


def reset() -> None:
    """Clear the per-process event registry (tests)."""
    _HOOKS.clear()
