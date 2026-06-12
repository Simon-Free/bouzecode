# [desc] Subprocess test verifying model access denied produces clean error message, not UnboundLocalError
# <tool_use name="FinalAnswer" id="f1"><param name="answer">Subprocess test verifying model access denied produces clean error message, not UnboundLocalError</param></tool_use> [/desc]
"""Subprocess test: model access denied produces clean error, not UnboundLocalError."""
import subprocess
import sys
import os

from tests.cache_conversation_helpers import require_api_key

BOUZECODE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def test_model_access_denied_no_crash():
    """Launch bouzecode with a model rejected by the proxy key.

    Expected: clean 'Model access denied' message, NOT UnboundLocalError.
    """
    require_api_key()  # live socle test — skips off VPN
    env = os.environ.copy()
    # Force a model the proxy rejects
    result = subprocess.run(
        [
            sys.executable, "-m", "bouzecode",
            "-m", "claude-sonnet-4-20250514",
            "-p", "say hello",
        ],
        capture_output=True,
        timeout=30,
        cwd=BOUZECODE_DIR,
        env=env,
    )

    # Decode as UTF-8 with replacement to handle ANSI escape sequences on Windows
    stdout = result.stdout.decode("utf-8", errors="replace") if result.stdout else ""
    stderr = result.stderr.decode("utf-8", errors="replace") if result.stderr else ""
    combined = stdout + stderr

    # The old bug: UnboundLocalError on auth_attempts
    assert "UnboundLocalError" not in combined, (
        f"Got UnboundLocalError (the old bug):\n{combined[-2000:]}"
    )

    # The fix: clean error message
    assert "Model access denied" in combined or "key_model_access_denied" in combined, (
        f"Expected 'Model access denied' in output but got:\n{combined[-2000:]}"
    )

    # Process should exit with non-zero (error)
    assert result.returncode != 0, "Expected non-zero exit code on auth error"
