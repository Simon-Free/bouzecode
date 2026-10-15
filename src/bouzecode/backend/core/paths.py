# [desc] Central registry for extra source directories injected via --extra-dir CLI flag. [/desc]
"""Central path registry for extra source directories.

Extra dirs follow the same structure as .bouzecode/:
  <dir>/skills/   → skills
  <dir>/mcp.json  → MCP servers
  <dir>/plugins/  → plugins
  <dir>/hooks/    → (future) hooks
"""
from __future__ import annotations

from pathlib import Path

_extra_dirs: list[Path] = []


def register_extra_dirs(dirs: list[Path | str]) -> None:
    """Register extra directories (called once at startup by main()). Deduplicates resolved paths."""
    global _extra_dirs
    seen: set[Path] = set()
    result: list[Path] = []
    for d in dirs:
        if d:
            p = Path(d).resolve()
            if p not in seen:
                seen.add(p)
                result.append(p)
    _extra_dirs = result


def _registre_agent(attribut: str) -> list[Path] | None:
    """La liste PROPRE au sous-agent en process qui s'execute (son atelier), ou None.

    Les sous-agents du TUI partagent ce process : un registre global faisait du worktree
    charge par l'un (LoadProjectConfig) une source de skills pour tous ses freres, d'ou
    chaque skill vue trois fois et autant d'avertissements « masquée par »."""
    from .dossier_agent import actif
    atelier = actif()
    return getattr(atelier, attribut) if atelier is not None else None


def add_extra_dir(path: Path | str) -> bool:
    """Append a single extra directory at runtime (no-op if already present). Returns True if added.

    Inside an in-process sub-agent the directory is recorded for THAT agent only."""
    resolved = Path(path).resolve()
    propre = _registre_agent("dossiers_extra")
    cible = propre if propre is not None else _extra_dirs
    if resolved in cible or resolved in _extra_dirs:
        return False
    cible.append(resolved)
    return True


def remove_extra_dir(path: Path | str) -> bool:
    """Drop a single extra directory from the in-memory registry. Returns True if removed."""
    global _extra_dirs
    resolved = Path(path).resolve()
    before = len(_extra_dirs)
    _extra_dirs = [d for d in _extra_dirs if d != resolved]
    propre = _registre_agent("dossiers_extra")
    retire_chez_l_agent = propre is not None and resolved in propre
    if retire_chez_l_agent:
        propre.remove(resolved)
    return len(_extra_dirs) != before or retire_chez_l_agent


def get_extra_dirs() -> list[Path]:
    """Return registered extra directories (highest priority sources): the process-wide
    ones, then those of the running sub-agent."""
    propre = _registre_agent("dossiers_extra") or []
    return list(_extra_dirs) + [d for d in propre if d not in _extra_dirs]


# --- Projects loaded in this session (LoadProjectConfig) --------------------
# Loading a project means "I am ALSO working in there". Skill scoping needs to know:
# a skill filed in <project>/.bouzecode/skills is scoped to <project>, so it would be
# filtered out when the agent's cwd is the parent monorepo. Registering the project
# here makes it an extra scope anchor — see tools/skill/scope.py::scope_anchors.

_loaded_projects: list[Path] = []


def register_loaded_project(path: Path | str) -> bool:
    """Record a project the agent has explicitly loaded. Returns True if newly added.

    Inside an in-process sub-agent the project is recorded for THAT agent only."""
    resolved = Path(path).resolve()
    propre = _registre_agent("projets")
    cible = propre if propre is not None else _loaded_projects
    if resolved in cible or resolved in _loaded_projects:
        return False
    cible.append(resolved)
    return True


def get_loaded_projects() -> list[Path]:
    """Projects loaded via LoadProjectConfig during this session (+ the running sub-agent's)."""
    propre = _registre_agent("projets") or []
    return list(_loaded_projects) + [p for p in propre if p not in _loaded_projects]


def clear_loaded_projects() -> None:
    """Forget every loaded project (tests only)."""
    _loaded_projects.clear()


# --- Persistence: extra dirs survive across runs via config.json's `extra_dirs` list. ---

def load_persisted_extra_dirs() -> list[str]:
    """Read the persisted extra-dir paths from config.json (raw strings, unresolved)."""
    from .config import load_config
    raw = load_config().get("extra_dirs", [])
    return [str(p) for p in raw if p]


def register_persisted_extra_dirs() -> None:
    """Register the persisted extra dirs into the in-memory registry (call at startup)."""
    for p in load_persisted_extra_dirs():
        add_extra_dir(p)


def persist_extra_dir(path: Path | str) -> tuple[bool, str]:
    """Validate, register in-memory, and persist a new extra dir. Returns (ok, message)."""
    from .config import load_config, save_config
    resolved = Path(path).expanduser()
    if not resolved.is_dir():
        return False, f"dossier introuvable : {path}"
    resolved = resolved.resolve()
    cfg = load_config()
    dirs = [str(p) for p in cfg.get("extra_dirs", [])]
    if str(resolved) in dirs:
        return False, f"déjà enregistré : {resolved}"
    dirs.append(str(resolved))
    cfg["extra_dirs"] = dirs
    save_config(cfg)
    add_extra_dir(resolved)
    return True, str(resolved)


def unpersist_extra_dir(path: Path | str) -> bool:
    """Remove an extra dir from config.json and the in-memory registry. Returns True if removed."""
    from .config import load_config, save_config
    resolved = str(Path(path).expanduser().resolve())
    cfg = load_config()
    dirs = [str(p) for p in cfg.get("extra_dirs", [])]
    kept = [p for p in dirs if str(Path(p).resolve()) != resolved and p != resolved]
    if len(kept) == len(dirs):
        return False
    cfg["extra_dirs"] = kept
    save_config(cfg)
    remove_extra_dir(resolved)
    return True
