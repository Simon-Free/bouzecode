# [desc] Single source of truth for the folder-map filename and its lock sidecar. [/desc]
"""Which file readme_sync maintains, and where its lock lives.

The name used to be the constant `AGENTS.md`, hard-coded in 26 places. This
repository's folder maps are named `README.md` and it ships no `AGENTS.md` at
all, so `python -m readme_sync --check` reported every single folder as MISSING
on a clean clone — the documented contributor command was unusable.

The name is now a setting, resolved once per run, most specific first:

1. `--doc-name AGENTS.md` on the command line;
2. the `README_SYNC_DOC_NAME` environment variable;
3. `[tool.readme_sync] doc_name = "..."` in the repo's `pyproject.toml`;
4. `README.md`, the default this repository uses.

The lock sidecar follows the name (`README.md` -> `.readme.lock`,
`AGENTS.md` -> `.agents.lock`), so the two can never disagree.
"""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

DEFAULT_DOC_NAME = "README.md"
ENV_DOC_NAME = "README_SYNC_DOC_NAME"
LOCK_VERSION = 1


def lock_name_for(doc_name: str) -> str:
    """`.<stem lowercased>.lock` — the sidecar that records the folder's hashes."""
    return f".{Path(doc_name).stem.lower()}.lock"


@dataclass(frozen=True)
class DocNaming:
    doc_name: str

    @property
    def lock_name(self) -> str:
        return lock_name_for(self.doc_name)


def _from_pyproject(root: Path) -> str | None:
    pyproject = root / "pyproject.toml"
    if not pyproject.exists():
        return None
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    configured = data.get("tool", {}).get("readme_sync", {}).get("doc_name")
    return configured or None


def resolve_naming(root: Path | None = None, override: str | None = None) -> DocNaming:
    """Apply the precedence above and return the naming for this run."""
    if override:
        return DocNaming(override)
    from_env = os.environ.get(ENV_DOC_NAME, "").strip()
    if from_env:
        return DocNaming(from_env)
    if root is not None:
        configured = _from_pyproject(root)
        if configured:
            return DocNaming(configured)
    return DocNaming(DEFAULT_DOC_NAME)


_active: DocNaming | None = None


def active() -> DocNaming:
    """The naming every module reads.

    Resolved from the environment / cwd on first use, so entry points that never
    call `use()` — the PostToolUse hook, a library import — still honour
    README_SYNC_DOC_NAME instead of silently falling back to the default."""
    global _active
    if _active is None:
        _active = resolve_naming(Path.cwd())
    return _active


def use(naming: DocNaming | None) -> DocNaming | None:
    """Install `naming` as the active one; returns the previous one (for tests).

    `use(None)` puts resolution back to lazy — how a test restores the state it
    found."""
    global _active
    previous = _active
    _active = naming
    return previous


def doc_name() -> str:
    return active().doc_name


def lock_name() -> str:
    return active().lock_name
