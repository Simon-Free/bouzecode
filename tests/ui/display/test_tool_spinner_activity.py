# [desc] The tool spinner must keep running while tools execute (the ToolStart->ToolEnd gap), not just while waiting on the LLM. [/desc]
"""Mirrors repl.py's spinner rules (no LLM): the consumer stops the spinner on any
stream-output event, restarts it at the end of each ToolStart handler so it animates
through the (event-less) tool execution, stops it for a permission prompt, and
restarts it after ToolEnd to cover the wait for the next LLM response.

Tools execute *after* the last ToolStart and emit no events until ToolEnd, so the
window we care about is "after the last ToolStart, before the first ToolEnd".
"""
from bouzecode.backend.agent.providers.types import ToolCallParsed, TextChunk
from bouzecode.backend.agent.state import ToolStart, ToolEnd, TurnDone, PermissionRequest

_STOP_ON = (TextChunk, ToolStart, ToolCallParsed, ToolEnd)


def _spinner_timeline(events, grant=True):
    """Return list of (event, spinner_on_after_handling) following repl.py's rules."""
    spinner_on = True  # started before streaming (repl.py:240)
    timeline = []
    for ev in events:
        if isinstance(ev, _STOP_ON) and spinner_on:
            spinner_on = False  # repl.py:256-258
        if isinstance(ev, ToolStart):
            spinner_on = True  # keep spinning through execution (the fix)
        elif isinstance(ev, PermissionRequest):
            spinner_on = False
            if grant:
                spinner_on = True
        elif isinstance(ev, ToolEnd):
            spinner_on = True  # repl.py:341 — wait for next LLM
        elif isinstance(ev, TurnDone):
            spinner_on = False  # repl.py:347
        timeline.append((ev, spinner_on))
    return timeline


def _spins_during_execution(events, grant=True):
    tl = _spinner_timeline(events, grant=grant)
    last_start = max(i for i, (e, _) in enumerate(tl) if isinstance(e, ToolStart))
    first_end = min(i for i, (e, _) in enumerate(tl) if isinstance(e, ToolEnd))
    # the execution window is the state right after the last ToolStart, up to ToolEnd
    return all(on for e, on in tl[last_start:first_end])


def test_spinner_runs_during_parallel_tool_execution():
    events = [
        TextChunk("Reading both files."),
        ToolCallParsed("Read", {"file_path": "a.py"}, "r1"),
        ToolCallParsed("Read", {"file_path": "b.py"}, "r2"),
        ToolStart("Read", {"file_path": "a.py"}, tool_id="r1"),
        ToolStart("Read", {"file_path": "b.py"}, tool_id="r2"),
        ToolEnd("Read", "content a", True, 0.1, tool_id="r1"),
        ToolEnd("Read", "content b", True, 0.1, tool_id="r2"),
    ]
    assert _spins_during_execution(events)


def test_spinner_runs_during_single_tool_execution():
    events = [
        ToolCallParsed("Bash", {"command": "pytest"}, "b1"),
        ToolStart("Bash", {"command": "pytest"}, tool_id="b1"),
        ToolEnd("Bash", "PASSED", True, 2.0, tool_id="b1"),
    ]
    assert _spins_during_execution(events)


def test_spinner_runs_after_granted_permission():
    events = [
        ToolStart("Write", {"file_path": "x.py"}, tool_id="w1"),
        PermissionRequest(description="Write x.py"),
        ToolEnd("Write", "ok", True, 0.1, tool_id="w1"),
    ]
    # After the user grants permission the tool runs; the spinner should resume.
    assert _spins_during_execution(events, grant=True)


def test_spinner_off_while_streaming_text():
    events = [TextChunk("hello"), TextChunk(" world")]
    tl = _spinner_timeline(events)
    assert all(not on for _, on in tl)
