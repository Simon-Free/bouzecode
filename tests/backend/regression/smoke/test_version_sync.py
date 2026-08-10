# [desc] Regression test ensuring cli.VERSION matches the package metadata version from pyproject.toml [/desc]
"""Regression test: cli.VERSION must match the package version from pyproject.toml."""
import importlib.metadata


def test_cli_version_matches_package_metadata():
    """VERSION in cli.py must equal importlib.metadata.version('bouzecode')."""
    from bouzecode.ui.cli import VERSION

    expected = importlib.metadata.version("bouzecode")
    assert VERSION == expected, (
        f"cli.py VERSION={VERSION!r} is stale; "
        f"package metadata says {expected!r}. "
        "VERSION should not be hardcoded."
    )
