# [desc] Tests that Methodology tool never signals ends_turn, preventing premature loop breaks in batches. [/desc]
"""
Regression test for the bug where Methodology had ends_turn=True,
causing the agent loop to break after every batch (since Methodology
is always present due to enforcement).
"""

from bouzecode.backend.core.tool_registry import get_tool, ends_turn


class TestMethodologyEndsTurn:
    """Methodology must not signal end-of-turn."""

    def test_methodology_ends_turn_is_false(self):
        """Methodology tool must have ends_turn=False."""
        # _register_builtins() is called at module load time (registration.py L220)
        # so importing bouzecode.backend.tools.registration triggers it
        import bouzecode.backend.tools.registration  # noqa: F401
        tool = get_tool("Methodology")
        assert tool is not None, "Methodology tool not registered"
        assert tool.ends_turn is False, (
            "Methodology must NOT have ends_turn=True — it causes premature "
            "loop breaks since Methodology is in every batch"
        )

    def test_batch_methodology_grep_does_not_end_turn(self):
        """A batch [Methodology, Grep] must NOT trigger the ends_turn check."""
        import bouzecode.backend.tools.registration  # noqa: F401
        batch = [{"name": "Methodology"}, {"name": "Grep"}]
        assert not any(ends_turn(tc["name"]) for tc in batch), (
            "Batch [Methodology, Grep] should not signal end of turn"
        )

    def test_batch_methodology_snippet_grep_does_not_end_turn(self):
        """A batch [Methodology, Snippet, Grep, Read] must NOT end turn."""
        import bouzecode.backend.tools.registration  # noqa: F401
        batch = [
            {"name": "Methodology"},
            {"name": "Snippet"},
            {"name": "Grep"},
            {"name": "Read"},
        ]
        assert not any(ends_turn(tc["name"]) for tc in batch), (
            "Normal working batch should not signal end of turn"
        )
