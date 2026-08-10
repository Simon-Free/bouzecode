# [desc] Tests that bouzecode is invocable via python -m with --help flag [/desc]
"""Test that bouzecode can be invoked via python -m."""
import subprocess
import sys


def test_python_m_bouzecode_help():
    """python -m bouzecode --help should exit 0."""
    result = subprocess.run(
        [sys.executable, "-m", "bouzecode", "--help"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert "usage" in result.stdout.lower() or "bouzecode" in result.stdout.lower()
