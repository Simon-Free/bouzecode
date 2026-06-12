# [desc] Tests that ends_turn uses any() semantics for mixed tool batches instead of all(). [/desc]
"""Tests for the ends_turn fix: any() instead of all() for mixed batches."""

from bouzecode.backend.core.tool_registry import (
    ToolDef,
    ends_turn,
    push_local_overlay,
    pop_local_overlay,
    register_tool,
)


class TestEndsTurnMixedBatch:
    """Verify that a batch containing at least one ends_turn tool signals end."""

    def setup_method(self):
        push_local_overlay()
        register_tool(ToolDef(
            name="Methodology", schema={}, func=lambda **kw: "",
            ends_turn=False, read_only=True, concurrent_safe=True,
        ))
        register_tool(ToolDef(
            name="final_answer", schema={}, func=lambda **kw: "",
            ends_turn=True, read_only=False, concurrent_safe=False,
        ))

    def teardown_method(self):
        pop_local_overlay()

    def test_mixed_batch_any_ends_turn(self):
        """Batch [Methodology, final_answer] must signal end via any()."""
        batch = [{"name": "Methodology"}, {"name": "final_answer"}]
        assert any(ends_turn(tc["name"]) for tc in batch) is True

    def test_mixed_batch_all_is_false(self):
        """Proves the bug: all() returned False for the same batch."""
        batch = [{"name": "Methodology"}, {"name": "final_answer"}]
        assert all(ends_turn(tc["name"]) for tc in batch) is False

    def test_only_non_ending_tools(self):
        """Batch of non-ending tools must NOT signal end."""
        register_tool(ToolDef(
            name="Read", schema={}, func=lambda **kw: "",
            ends_turn=False, read_only=True, concurrent_safe=True,
        ))
        batch = [{"name": "Methodology"}, {"name": "Read"}]
        assert any(ends_turn(tc["name"]) for tc in batch) is False

    def test_single_ending_tool(self):
        """Batch with only final_answer signals end (no regression)."""
        batch = [{"name": "final_answer"}]
        assert any(ends_turn(tc["name"]) for tc in batch) is True

    def test_single_non_ending_tool(self):
        """Batch with only Methodology does NOT signal end."""
        batch = [{"name": "Methodology"}]
        assert any(ends_turn(tc["name"]) for tc in batch) is False
