# [desc] E2E test verifying model access denied errors produce clean messages instead of UnboundLocalError
# <tool_use name="FinalAnswer" id="f1"><param name="answer">E2E test verifying model access denied errors produce clean messages instead of UnboundLocalError</param></tool_use> [/desc]
"""E2E test: verify model access denied errors are handled cleanly (no UnboundLocalError)."""

import subprocess
import sys
import os

import pytest
from pathlib import Path

from tests.cache_conversation_helpers import require_api_key

# tests/backend/providers/auth/<file> -> repo root is 4 parents up.
BOUZECODE_DIR = str(Path(__file__).resolve().parents[4])


def test_model_access_denied_no_crash():
    """When the API key doesn't allow the requested model, bouzecode should
    display a clean error message instead of crashing with UnboundLocalError."""
    require_api_key()
    result = subprocess.run(
        [
            sys.executable, "-m", "bouzecode",
            "-p",  # print mode (non-interactive, run and exit)
            "-m", "claude-sonnet-4-20250514",  # model rejected by proxy key
            "hello",
        ],
        cwd=BOUZECODE_DIR,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",  # banner/glyphs are UTF-8; default cp1252 crashes the reader
        timeout=30,
    )

    combined = (result.stdout or "") + (result.stderr or "")

    # MUST NOT have the old UnboundLocalError
    assert "UnboundLocalError" not in combined, (
        f"Got UnboundLocalError crash!\nstderr:\n{result.stderr}"
    )

    # Should show the model access denied error cleanly
    assert (
        "Model access denied" in combined
        or "not allowed to access model" in combined
        or "key_model_access_denied" in combined
    ), f"Expected model access error message.\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
