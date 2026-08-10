"""Tests for bouzecode_version resolution from pyproject.toml.

Verifies that _get_bouzecode_version() returns the real version
from pyproject.toml [project].version, not 'unknown'.
"""

import tomllib
from pathlib import Path

from bouzecode.backend.agent.loop import _get_bouzecode_version


def _read_pyproject_version() -> str:
    """Read version directly from pyproject.toml for comparison."""
    repo_root = Path(__file__).resolve()
    for _ in range(10):
        repo_root = repo_root.parent
        candidate = repo_root / "pyproject.toml"
        if candidate.is_file():
            with open(candidate, "rb") as f:
                data = tomllib.load(f)
            return data["project"]["version"]
    raise FileNotFoundError("pyproject.toml not found walking up from test file")


def test_version_matches_pyproject():
    """_get_bouzecode_version() returns exactly the version from pyproject.toml."""
    expected = _read_pyproject_version()
    actual = _get_bouzecode_version()
    assert actual == expected, f"Expected {expected!r}, got {actual!r}"


def test_version_is_not_unknown():
    """_get_bouzecode_version() does not return 'unknown' in this repo."""
    version = _get_bouzecode_version()
    assert version != "unknown", (
        "Version should be resolved from pyproject.toml, got 'unknown'"
    )
