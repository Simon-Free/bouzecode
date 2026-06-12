"""Diagnostic test: why does the loop send a second API call after Methodology-only response?

Hypotheses to verify:
1. ends_turn("Methodology") returns False → loop continues
2. build_minimal_payload strips the tool_result → empty messages → 500
"""


def test_methodology_ends_turn_value():
    """Check if Methodology is registered and whether it has ends_turn=True."""
    from bouzecode.backend.core.tool_registry import get_tool, ends_turn
    tool = get_tool("Methodology")
    print(f"Methodology tool object: {tool}")
    print(f"ends_turn('Methodology'): {ends_turn('Methodology')}")
    if tool:
        print(f"  tool.name={tool.name}, tool.ends_turn={tool.ends_turn}")
    assert tool is not None, "Methodology tool is not registered at all!"


def test_build_minimal_payload_after_methodology():
    """Simulate state after Methodology executed, check what build_messages_for_api returns."""
    from bouzecode.backend.agent.minimal_payload import build_messages_for_api

    class FakeState:
        def __init__(self):
            self.messages = [
                {"role": "user", "content": "test"},
                {
                    "role": "assistant",
                    "content": "Bien reçu !",
                    "tool_calls": [{"id": "m1", "name": "Methodology", "input": {"content": "session start"}}],
                },
                {
                    "role": "tool",
                    "tool_call_id": "m1",
                    "name": "Methodology",
                    "content": "OK",
                },
            ]

    state = FakeState()
    config = {}
    result = build_messages_for_api(state, config)
    print(f"build_messages_for_api result ({len(result)} messages):")
    for i, msg in enumerate(result):
        role = msg.get("role", "?")
        content = str(msg.get("content", ""))[:80]
        print(f"  [{i}] role={role} content={content!r}")

    # The API requires at least one message
    assert len(result) > 0, "build_messages_for_api returned EMPTY list — this causes the 500!"
    # Check it contains a proper structure (not just a lone tool_result)
    roles = [m["role"] for m in result]
    print(f"  roles: {roles}")
    # Anthropic requires messages to start with user or have assistant before tool_result
    assert roles[0] in ("user", "assistant"), f"First message role is {roles[0]}, API will reject this"


def test_loop_turn_any_vs_all_ends_turn():
    """Document the any() check at loop_turn.py L425 vs all() in hooks/ends_turn.py."""
    from bouzecode.backend.core.tool_registry import ends_turn

    # If Methodology has ends_turn=False, the any() check won't trigger
    methodology_ends = ends_turn("Methodology")
    snippet_ends = ends_turn("Snippet")
    print(f"ends_turn('Methodology') = {methodology_ends}")
    print(f"ends_turn('Snippet') = {snippet_ends}")

    # This is the condition at loop_turn.py L425
    tool_calls = [{"name": "Methodology"}]
    any_ends = any(ends_turn(tc["name"]) for tc in tool_calls)
    print(f"any(ends_turn) for [Methodology] = {any_ends}")

    # If False → loop continues → second API call → potential 500
    # Fix: either mark Methodology ends_turn=True, or add special case
