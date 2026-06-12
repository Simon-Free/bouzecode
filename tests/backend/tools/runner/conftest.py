"""Runner tests require pytest to be spawnable via `uv run --no-sync pytest`.

Skip all tests in this directory when the environment can't spawn pytest
(e.g. no venv activated, no uv available).
"""
import subprocess
import pytest

def _can_spawn_pytest():
    """Check if pytest can be spawned via uv."""
    try:
        r = subprocess.run(
            ["uv", "run", "--no-sync", "pytest", "--version"],
            capture_output=True, timeout=10,
        )
        return r.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False

_PYTEST_AVAILABLE = _can_spawn_pytest()

def pytest_collection_modifyitems(config, items):
    """Skip runner tests that spawn pytest when it's not available."""
    if _PYTEST_AVAILABLE:
        return
    skip_marker = pytest.mark.skip(reason="pytest not spawnable via `uv run --no-sync pytest` in this environment")
    for item in items:
        # Only affect tests IN THIS directory (runner/)
        if "tools/runner/" not in str(item.fspath).replace("\\", "/"):
            continue
        # Only skip tests that actually spawn pytest (not pure regex unit tests)
        if "TestProgressRegexes" not in str(item.nodeid):
            item.add_marker(skip_marker)
