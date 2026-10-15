"""RunPythonTest --testmon: run ONLY the tests affected by the changed code.

Measured on the bouzecode suite (2026-09-08), folder tests/backend/tools, 343 tests,
-n auto: full run 68.1s -> incremental run with nothing changed 4.1s (-94%).

The trap this file exists to prevent (paid for over two full turns of measuring
nothing): testmon SILENTLY disables its selection as soon as `-m` is on the command
line -- it prints `testmon: selection automatically deactivated because -m was used`
and runs everything, coverage overhead (+34%) included, gain zero.

bouzecode's pyproject carries `addopts = "-m 'not web and not ui'"` PERMANENTLY, so
every `uv run pytest` inherits a `-m`. A testmon mode that does not neutralise
addopts is therefore pure cost. Hence: `-o addopts=` is injected, and an explicit
`marker` is REFUSED instead of being silently ignored.
"""

import textwrap
from pathlib import Path

import pytest

from bouzecode.backend.tools.ops.test_runner import (
    _with_pytest_overlay,
    _with_testmon_overlay,
    run_python_test,
)


class TestTestmonOverlay:
    """pytest-testmon is provided by an EPHEMERAL uv overlay, never installed.

    The project venv is shared with the server and the other agents: writing to it
    (uv sync / pip install) would change everyone's environment.
    """

    def test_with_flag_is_inserted_right_after_uv_run(self):
        cmd = ["uv", "run", "--no-sync", "--directory", "/repo", "pytest", "-v"]
        assert _with_testmon_overlay(cmd) == [
            "uv",
            "run",
            "--with",
            "pytest-testmon",
            "--no-sync",
            "--directory",
            "/repo",
            "pytest",
            "-v",
        ]

    def test_original_command_is_not_mutated(self):
        cmd = ["uv", "run", "pytest"]
        _with_testmon_overlay(cmd)
        assert cmd == ["uv", "run", "pytest"]

    def test_overlay_is_idempotent(self):
        cmd = ["uv", "run", "--with", "pytest-testmon", "pytest"]
        assert _with_testmon_overlay(cmd) == cmd

    def test_overlay_never_asks_uv_to_sync(self):
        overlaid = _with_testmon_overlay(["uv", "run", "--no-sync", "pytest"])
        assert "--no-sync" in overlaid
        assert "sync" not in [p for p in overlaid if p != "--no-sync"]


class TestMissingPytestFallbackStillWorksUnderTestmon:
    """The testmon overlay must not disarm the missing-pytest rescue.

    `_with_pytest_overlay` used to bail out on ANY `--with`. In testmon mode a
    `--with pytest-testmon` is always present, so bailing out would leave the agent
    with the raw `No module named '_pytest'` traceback it cannot act on.
    """

    def test_pytest_is_still_added_when_only_testmon_is_overlaid(self):
        overlaid = _with_pytest_overlay(["uv", "run", "--with", "pytest-testmon", "pytest"])
        assert "pytest-testmon" in overlaid
        assert "pytest" in overlaid[2:6]
        assert "pytest-xdist" in overlaid

    def test_still_idempotent_once_pytest_itself_is_overlaid(self):
        cmd = ["uv", "run", "--with", "pytest-testmon", "--with", "pytest", "pytest"]
        assert _with_pytest_overlay(cmd) == cmd


class TestMarkerIsRefusedNotIgnored:
    def test_testmon_with_marker_fails_fast(self):
        out = run_python_test(targets=["tests"], testmon=True, marker="not web")
        assert out.startswith("Error:")
        assert "testmon" in out
        assert "-m" in out or "marker" in out

    def test_error_is_returned_without_running_anything(self):
        out = run_python_test(targets=["tests"], testmon=True, marker="backend")
        assert "test session starts" not in out


@pytest.fixture
def mini_project(tmp_path):
    """A real project whose addopts carries a `-m`, exactly like bouzecode's."""
    (tmp_path / "pyproject.toml").write_text(
        textwrap.dedent(
            """\
            [project]
            name = "tm-probe"
            version = "0.1.0"
            requires-python = ">=3.10"

            [tool.pytest.ini_options]
            testpaths = ["tests"]
            markers = ["web: set aside"]
            addopts = "-m 'not web'"
            """
        ),
        encoding="utf-8",
    )
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_probe.py").write_text(
        "def test_ok():\n    assert True\n", encoding="utf-8"
    )
    # `uv run --with pytest-testmon` has to REACH the index to materialise the
    # plugin, and this machine only goes out through an authenticated proxy.
    # run_python_test() loads <project_root>/.env, so hand the mini-project the
    # proxy lines ONLY -- never the whole .env, which holds credentials.
    repo_env = Path(__file__).resolve().parents[4] / ".env"
    if repo_env.exists():
        proxy_lines = [
            line
            for line in repo_env.read_text(encoding="utf-8", errors="replace").splitlines()
            if "_proxy" in line.split("=", 1)[0].lower() and "=" in line
        ]
        if proxy_lines:
            (tmp_path / ".env").write_text("\n".join(proxy_lines) + "\n", encoding="utf-8")
    return tmp_path


def _skip_if_network_blocked(out: str) -> None:
    """An unreachable package index is not a regression of the tool under test."""
    for signature in ("Failed to fetch", "proxy authorization required", "No solution found"):
        if signature in out:
            pytest.skip(f"uv could not materialise pytest-testmon ({signature})")


class TestSelectionEndToEnd:
    """Two real runs through the tool: build the DB, then re-run with nothing changed."""

    def test_second_run_deselects_everything(self, mini_project):
        target = str(mini_project / "tests" / "test_probe.py")

        first = run_python_test(targets=[target], parallel="off", testmon=True, timeout=300)
        assert "--testmon" in first
        # addopts neutralised, otherwise testmon deactivates its own selection
        assert "addopts=" in first
        _skip_if_network_blocked(first)
        assert "1 passed" in first, first[-1500:]

        second = run_python_test(targets=[target], parallel="off", testmon=True, timeout=300)
        assert "deselected" in second, second[-1500:]
