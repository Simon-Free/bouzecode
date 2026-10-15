# [desc] Resolves bouzecode data/project dirs and BOUZECODE_* env vars [/desc]
"""Data-dir / env helpers.

Every place that needs the user data directory, a per-project config directory or a
``BOUZECODE_*`` environment variable goes through this module.

Stdlib only: imported very early (from ``bouzecode/__init__``).
"""
from __future__ import annotations

import os
from pathlib import Path

DATA_DIR_NAME = ".bouzecode"
PROJECT_DIR_NAMES: tuple[str, ...] = (DATA_DIR_NAME,)

ENV_PREFIX = "BOUZECODE_"


def data_dir(home: Path | str | None = None) -> Path:
    """User data directory: ``~/.bouzecode``."""
    base = Path(home) if home is not None else Path.home()
    return base / DATA_DIR_NAME


def project_dir(base: Path | str) -> Path:
    """Per-project config dir: ``<base>/.bouzecode``."""
    return Path(base) / DATA_DIR_NAME


def project_dirs(base: Path | str) -> list[Path]:
    """Candidate project dirs under *base*."""
    base = Path(base)
    return [base / name for name in PROJECT_DIR_NAMES]


def legacy_env_name(name: str) -> str | None:
    """Kept for API compatibility: there is no legacy prefix."""
    return None


def getenv(name: str, default: str | None = None) -> str | None:
    """Read an environment variable."""
    return os.environ.get(name, default)


def mirror_legacy_env(environ=None) -> None:
    """Kept for API compatibility: nothing to mirror."""
    return None
