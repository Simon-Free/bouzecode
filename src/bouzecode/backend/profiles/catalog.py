"""Remote shared agent catalog (demo_agents) — backend layer.

Pulls a git repo of agent profiles on demand into ~/.bouzecode/agent_catalog/,
then exposes the available/installed split. Shared foundation for CLI + UI.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Dict, Tuple

from ..core.config import CONFIG_DIR
from ..multi_agent.plugin_resolver import _normalize
from ..plugin import store
from . import discovery, loader
from .models import AgentProfile

CATALOG_DIR = CONFIG_DIR / "agent_catalog"
PROFILES_SUBDIR = "profiles"

_ENV_URL = "BOUZECODE_AGENT_CATALOG_URL"
_ENV_GITLAB = "GITLAB_DEMO_URL"
_CATALOG_PATH = "/demo_plugins/demo_agents.git"


def _catalog_url() -> str:
    """Resolve the catalog repo URL. Never hardcoded.

    Order: BOUZECODE_AGENT_CATALOG_URL > GITLAB_DEMO_URL-derived >
    settings.gitlab_url-derived. Raises RuntimeError if none available.
    """
    explicit = os.environ.get(_ENV_URL)
    if explicit:
        return explicit
    base = os.environ.get(_ENV_GITLAB)
    if not base:
        try:
            from ..core.config import get_settings  # type: ignore

            base = getattr(get_settings(), "gitlab_url", "") or ""
        except Exception:
            base = ""
    if base:
        return base.rstrip("/") + _CATALOG_PATH
    raise RuntimeError(
        f"Cannot resolve agent catalog URL: set {_ENV_URL} or {_ENV_GITLAB}."
    )


def _profiles_dir() -> Path:
    return CATALOG_DIR / PROFILES_SUBDIR


def refresh_catalog(force: bool = False) -> Path:
    """Clone (first time) or git pull --ff-only the catalog repo.

    Returns the catalog directory on success. On fetch failure the existing
    cache is left intact and a RuntimeError is raised (never swallowed).
    """
    url = _catalog_url()
    CATALOG_DIR.parent.mkdir(parents=True, exist_ok=True)
    git_dir = CATALOG_DIR / ".git"
    if git_dir.is_dir() and not force:
        pull = subprocess.run(
            ["git", "-C", str(CATALOG_DIR), "pull", "--ff-only"],
            capture_output=True,
            text=True,
        )
        if pull.returncode != 0:
            raise RuntimeError(
                f"git pull failed for agent catalog {CATALOG_DIR}: "
                f"{pull.stderr.strip()}"
            )
    else:
        clone = subprocess.run(
            ["git", "clone", "--depth", "1", url, str(CATALOG_DIR)],
            capture_output=True,
            text=True,
        )
        if clone.returncode != 0:
            raise RuntimeError(f"git clone failed for agent catalog: {clone.stderr.strip()}")
    return CATALOG_DIR


def list_catalog_profiles() -> Dict[str, AgentProfile]:
    """Parse agent_catalog/profiles/*.yaml into AgentProfiles."""
    return loader.load_profiles_from_dir(_profiles_dir())


def is_installed(profile: AgentProfile) -> bool:
    """True if every required plugin is present locally.

    A required plugin matches an installed PluginEntry by package OR name
    (after normalization). A profile with no requires_plugins is installed.
    """
    required = getattr(profile, "requires_plugins", None) or []
    if not required:
        return True
    installed = store.list_plugins()
    names = {e.name for e in installed} | {e.package for e in installed}
    for req in required:
        pkg, _src = _normalize(req)
        if pkg not in names:
            return False
    return True


def installed_and_available() -> Tuple[Dict[str, AgentProfile], Dict[str, AgentProfile]]:
    """Return (installed, available).

    'installed' = catalog profiles whose plugins are all present, PLUS every
    local user profile (always considered installed even if absent from the
    catalog). 'available' = catalog profiles not yet installed.
    """
    catalog = list_catalog_profiles()
    installed: Dict[str, AgentProfile] = {}
    available: Dict[str, AgentProfile] = {}
    for name, profile in catalog.items():
        if is_installed(profile):
            installed[name] = profile
        else:
            available[name] = profile
    # Local profiles are always installed (may shadow catalog entries).
    installed.update(discovery.load_user_profiles())
    return installed, available
