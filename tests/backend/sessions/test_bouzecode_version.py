"""Tests for bouzecode_version resolution from pyproject.toml.

Verifies that _get_bouzecode_version() returns a valid version string
(not 'unknown') from pyproject.toml [project].version.
"""

import re

from bouzecode.backend.agent.loop import _get_bouzecode_version


_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+")


def test_version_is_valid_semver():
    """_get_bouzecode_version() returns a valid semver, not 'unknown'."""
    actual = _get_bouzecode_version()
    assert actual != "unknown", "Version resolution failed — returned 'unknown'"
    assert _SEMVER_RE.match(actual), f"Version {actual!r} is not valid semver"


def test_version_is_not_unknown():
    """_get_bouzecode_version() does not return 'unknown' in this repo."""
    version = _get_bouzecode_version()
    assert version != "unknown", (
        "Version should be resolved from pyproject.toml, got 'unknown'"
    )
