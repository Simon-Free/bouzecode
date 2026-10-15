# [desc] Tests that _bash timeout error messages contain scaling hints and RunPythonTest guidance. [/desc]
import os

from bouzecode.backend.tools.ops.shell_search import _bash


def _sleep(seconds: int) -> str:
    """A slow command for the platform's shell (Bash runs through PowerShell on Windows)."""
    return f"powershell -Command Start-Sleep {seconds}" if os.name == "nt" else f"sleep {seconds}"


def test_timeout_message_contains_hint():
    """A real slow process triggers timeout; message must contain guidance."""
    result = _bash(_sleep(5), timeout=1)
    # Basic structure
    assert "timed out after 1s" in result
    # Hint about increasing timeout
    assert "timeout=4" in result
    # Hint about RunPythonTest
    assert "RunPythonTest" in result


def test_timeout_message_multiplier_scales():
    """The suggested timeout should be 4x the original."""
    result = _bash(_sleep(10), timeout=2)
    assert "timeout=8" in result


def test_empty_output_rc0_stamps_warning():
    """rc=0 with empty stdout+stderr must stamp the explicit empty-output warning."""
    result = _bash("exit 0")
    assert "\u26a0\ufe0f" in result
    assert "sortie vide" in result
    assert "(no output)" not in result


def test_nonempty_output_rc0_no_warning():
    """rc=0 with real output must NOT trigger the empty-output warning (no false positive)."""
    result = _bash("echo hello")
    assert "hello" in result
    assert "sortie vide" not in result


def test_nonzero_rc_empty_output_no_empty_warning():
    """rc!=0 with empty output must keep normal behavior, NOT the empty-output warning."""
    result = _bash("exit 3")
    assert "sortie vide" not in result
