# [desc] Tests that default stream stall timeouts are 60s first-event and 15s inter-chunk in a clean subprocess [/desc]
"""Default stall deadlines, read in a fresh interpreter so no env var leaks in.

Decision of 2026-10-12: a prompt is ingested within 60 s, and once the stream has
started (thinking, text, tool input arrive continuously) 15 s of silence is a real
stall worth retrying early instead of waiting minutes."""
import os
import subprocess
import sys

_ENV_VARS = (
    "BOUZECODE_INTER_CHUNK_TIMEOUT_S",
    "BOUZECODE_FIRST_EVENT_TIMEOUT_S",
    "BOUZECODE_STREAM_FIRST_PROGRESS_TIMEOUT_S",
    "BOUZECODE_STREAM_PROGRESS_TIMEOUT_S",
)

_PROBE = (
    "from bouzecode.backend.agent.providers.backends import anthropic_helpers as a\n"
    "from bouzecode.backend.agent.providers.backends.stream_progress import progress_timeouts\n"
    "print(a._FIRST_EVENT_TIMEOUT_S, a._INTER_CHUNK_TIMEOUT_S, *progress_timeouts({}))\n"
)


def test_default_stall_timeouts_are_60s_first_event_and_15s_between_events():
    env = {k: v for k, v in os.environ.items() if k not in _ENV_VARS}
    out = subprocess.run(
        [sys.executable, "-c", _PROBE], env=env, capture_output=True, text=True,
        timeout=120,
    )
    assert out.returncode == 0, out.stderr
    assert out.stdout.split() == ["60", "15", "60.0", "15.0"]
