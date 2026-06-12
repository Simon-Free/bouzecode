# [desc] Tests that concurrent _append_block calls from multiple threads do not lose data due to race conditions
# <tool_use name="FinalAnswer" id="r1"><param name="answer">Tests that concurrent _append_block calls from multiple threads do not lose data due to race conditions</param></tool_use> [/desc]
"""Test that _append_block has a race condition when called from multiple threads.

This reproduces the bug: concurrent Snippet/Methodology tools calling _append_block
in parallel lose data because of non-atomic read-modify-write on context_state.notes.
"""
import threading
from concurrent.futures import ThreadPoolExecutor

from bouzecode.backend.context_manager.methodology import _append_block


class FakeContextState:
    """Minimal ContextState stand-in with just a notes dict."""
    def __init__(self):
        self.notes = {}


def test_append_block_race_condition():
    """Parallel _append_block calls lose data due to read-modify-write race.

    This test spawns 20 threads that each append a unique block.
    With the race condition, some blocks are lost (last-writer-wins).
    """
    context_state = FakeContextState()
    n_threads = 20
    barrier = threading.Barrier(n_threads)

    def append_one(i: int):
        # Barrier ensures all threads start simultaneously to maximize race window
        barrier.wait()
        _append_block(context_state, f"BLOCK_{i:03d}")

    with ThreadPoolExecutor(max_workers=n_threads) as pool:
        futures = [pool.submit(append_one, i) for i in range(n_threads)]
        for f in futures:
            f.result()

    methodology = context_state.notes.get("methodology", "")
    # Check that ALL blocks survived
    missing = [i for i in range(n_threads) if f"BLOCK_{i:03d}" not in methodology]
    assert not missing, (
        f"Race condition confirmed: {len(missing)}/{n_threads} blocks lost. "
        f"Missing: {missing[:5]}{'...' if len(missing) > 5 else ''}"
    )
