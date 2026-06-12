# [desc] Tests inline tool display ordering and ToolCallParsed/ToolStart event deduplication during streaming
# <tool_use name="FinalAnswer" id="f1"><param name="answer">Tests inline tool display ordering and ToolCallParsed/ToolStart event deduplication during streaming</param></tool_use> [/desc]
"""Test inline tool display ordering — ToolCallParsed events during streaming."""


def test_tool_call_parsed_fields():
    from bouzecode.backend.agent.providers.types import ToolCallParsed

    tcp = ToolCallParsed("Write", {"file_path": "out.py"}, "w1")
    assert tcp.name == "Write"
    assert tcp.inputs == {"file_path": "out.py"}
    assert tcp.tool_id == "w1"


def test_tool_start_default_tool_id():
    from bouzecode.backend.agent.state import ToolStart

    ts = ToolStart("Read", {"file_path": "test.py"})
    assert ts.tool_id == ""


def test_tool_start_with_tool_id():
    from bouzecode.backend.agent.state import ToolStart

    ts = ToolStart("Read", {"file_path": "test.py"}, tool_id="r1")
    assert ts.tool_id == "r1"


def test_inline_shown_skips_tool_start():
    """ToolCallParsed shown inline → ToolStart display should be skipped."""
    from bouzecode.backend.agent.providers.types import ToolCallParsed, TextChunk
    from bouzecode.backend.agent.state import ToolStart, ToolEnd

    events = [
        TextChunk("Let me read the file."),
        ToolCallParsed("Read", {"file_path": "test.py"}, "r1"),
        TextChunk("Now analyzing..."),
        ToolCallParsed("Bash", {"command": "pytest"}, "b1"),
        ToolStart("Read", {"file_path": "test.py"}, tool_id="r1"),
        ToolEnd("Read", "file content", True, 0.1),
        ToolStart("Bash", {"command": "pytest"}, tool_id="b1"),
        ToolEnd("Bash", "PASSED", True, 0.5),
    ]

    shown_inline = set()
    shown_at_start = set()

    for ev in events:
        if isinstance(ev, ToolCallParsed):
            shown_inline.add(ev.tool_id)
        elif isinstance(ev, ToolStart):
            if ev.tool_id not in shown_inline:
                shown_at_start.add(ev.tool_id)

    assert shown_inline == {"r1", "b1"}
    assert shown_at_start == set()


def test_tool_start_shown_when_no_inline():
    """ToolStart without prior ToolCallParsed should still display."""
    from bouzecode.backend.agent.state import ToolStart

    shown_inline: set[str] = set()
    event = ToolStart("Read", {"file_path": "x.py"}, tool_id="r1")
    assert event.tool_id not in shown_inline


def test_event_ordering_simulation():
    """Full repl-like event flow: text and tools interspersed correctly."""
    from bouzecode.backend.agent.providers.types import ToolCallParsed, TextChunk
    from bouzecode.backend.agent.state import ToolStart, ToolEnd, TurnDone

    _shown_inline_ids: set[str] = set()
    displayed: list[tuple] = []

    events = [
        TextChunk("Let me read..."),
        ToolCallParsed("Read", {"file_path": "a.py"}, "r1"),
        TextChunk("And this too..."),
        ToolCallParsed("Read", {"file_path": "b.py"}, "r2"),
        TurnDone(1000, 500, 800, 200),
        ToolStart("Read", {"file_path": "a.py"}, tool_id="r1"),
        ToolEnd("Read", "content a", True, 0.1),
        ToolStart("Read", {"file_path": "b.py"}, tool_id="r2"),
        ToolEnd("Read", "content b", True, 0.1),
    ]

    for ev in events:
        if isinstance(ev, TextChunk):
            displayed.append(("text", ev.text))
        elif isinstance(ev, ToolCallParsed):
            displayed.append(("tool_inline", ev.name, ev.tool_id))
            _shown_inline_ids.add(ev.tool_id)
        elif isinstance(ev, ToolStart):
            if ev.tool_id not in _shown_inline_ids:
                displayed.append(("tool_start", ev.name, ev.tool_id))
        elif isinstance(ev, ToolEnd):
            displayed.append(("tool_end", ev.name))

    types = [d[0] for d in displayed]
    assert types == ["text", "tool_inline", "text", "tool_inline", "tool_end", "tool_end"]
    assert "tool_start" not in types
