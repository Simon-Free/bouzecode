# [desc] Central profile discovery: the ordered list of dirs profiles are loaded from (builtin < user-global < project < extra-dirs) and helpers to load them. [/desc]
"""One source of truth for *where* agent profiles live, so the CLI (/agent), the
sub-agent spawner and the web builder all resolve the same set.

Precedence (later overrides earlier): bouzecode builtins < ~/.bouzecode (global,
accessible everywhere) < <cwd>/.bouzecode (project) < registered --extra-dir paths.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict

from bouzecode.backend.profiles import loader as _loader
from bouzecode.backend.profiles.models import AgentProfile


def user_global_dir() -> Path:
    from bouzecode.backend.core.config import CONFIG_DIR
    return CONFIG_DIR / "profiles"


def builtin_dir() -> Path:
    """Directory holding bouzecode-shipped builtin profiles (system agents + fragments)."""
    return Path(__file__).resolve().parent / "builtin"


def load_system_profiles() -> Dict[str, AgentProfile]:
    """Builtin profiles marked `kind: system` — the always-present switchable system
    agents (general-purpose, meta-agent, manager). Composable fragments like `deferred`
    (`kind: fragment`) are excluded, so they stay merge-only and never appear as agents."""
    return {n: p for n, p in _loader.load_profiles_from_dir(builtin_dir()).items()
            if p.kind == "system"}


def resolve_agent_profile(name: str) -> AgentProfile | None:
    """Single resolution point for the `/agent` switch and the Agent() spawn path.

    Looks up system builtins first, then user/project/extra/catalog-installed profiles
    (the latter win on name collision, so a project can shadow a system agent)."""
    return {**load_system_profiles(), **load_user_profiles()}.get(name)


def profile_search_dirs(include_builtin: bool = False) -> list[Path]:
    """Profile dirs in precedence order (lowest first)."""
    from bouzecode.backend.core.paths import get_extra_dirs

    dirs: list[Path] = []
    if include_builtin:
        dirs.append(Path(__file__).resolve().parent / "builtin")
    dirs.append(user_global_dir())
    dirs.append(Path.cwd() / ".bouzecode" / "profiles")
    dirs.extend(d / "profiles" for d in get_extra_dirs())
    return dirs


def _load(dirs: list[Path]) -> Dict[str, AgentProfile]:
    available: Dict[str, AgentProfile] = {}
    for directory in dirs:
        available.update(_loader.load_profiles_from_dir(directory))
    return available


def load_user_profiles() -> Dict[str, AgentProfile]:
    """User-authored profiles (global + project + extra-dirs) — the directly switchable set.

    `kind: app` profiles (standalone host-app agents) are excluded: their host
    loads them DIRECTLY by path and routes to them as a single agent — they are never
    switched to (/agent) nor spawned as bouzecode sub-agents. This keeps the shared profile
    FORMAT while stopping app agents from leaking into the dev agent set."""
    return {n: p for n, p in _load(profile_search_dirs(include_builtin=False)).items()
            if p.kind != "app"}


def load_all_profiles() -> Dict[str, AgentProfile]:
    """Everything resolvable by name, incl. composable bouzecode builtins (deferred…)."""
    return _load(profile_search_dirs(include_builtin=True))
