# [desc] Tests that cli.VERSION matches the version declared in package metadata (pyproject.toml). [/desc]
"""Test that cli.VERSION matches the package metadata version."""
import importlib.metadata


def test_cli_version_matches_package():
    """cli.VERSION must equal the version declared in pyproject.toml (via metadata)."""
    from bouzecode.ui.cli import VERSION

    try:
        expected = importlib.metadata.version("bouzecode")
    except importlib.metadata.PackageNotFoundError:
        expected = importlib.metadata.version("bouzecode")  # venv not reinstalled
    assert VERSION == expected, (
        f"cli.VERSION={VERSION!r} != metadata version={expected!r}. "
        "VERSION in cli.py is probably hardcoded and out of sync."
    )
