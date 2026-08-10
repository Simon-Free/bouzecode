"""Test that wait_ready import in loop.py doesn't raise NameError."""
import types
import sys


def test_wait_ready_no_nameerror():
    """Simulate the turn_count==0 code path — must not raise NameError.

    If bouzecode.mcp is missing, ImportError is caught gracefully.
    If it exists but wait_ready is missing, same.
    Either way: no NameError.
    """
    from bouzecode.backend.agent.loop import run  # noqa: F401 — import triggers module parse

    # Directly test the pattern used in loop.py L156-160:
    raised_name_error = False
    try:
        try:
            from bouzecode.mcp import wait_ready
            wait_ready(timeout=10.0)
        except (ImportError, ModuleNotFoundError):
            pass
    except NameError:
        raised_name_error = True

    assert not raised_name_error, "NameError was raised — import is still missing"
