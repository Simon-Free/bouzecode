"""Tests for the SNIPPET_MIN_LINES threshold across enforcement, wire, and recovery."""
import pytest

from bouzecode.backend.agent.snippet_wire import (
    SNIPPET_MIN_LINES,
    wrap_snippetable,
    wrap_file_snippetable,
    _line_count,
    _SNIPPET_OPEN,
    _FILE_SNIPPET_OPEN,
    _SNIPPET_CLOSE,
)


# ---------------------------------------------------------------------------
# Helper to build lines of content
# ---------------------------------------------------------------------------

def _make_content(n_lines: int) -> str:
    """Create content with exactly n_lines lines."""
    return "\n".join(f"line {i}" for i in range(1, n_lines + 1))


# ---------------------------------------------------------------------------
# Tests: _line_count
# ---------------------------------------------------------------------------

class TestLineCount:
    def test_no_content_counts_zero_lines(self):
        """Un resultat vide compte zero ligne."""
        assert _line_count("") == 0

    def test_text_without_newline_counts_one_line(self):
        """Un texte sans retour a la ligne compte une ligne."""
        assert _line_count("hello") == 1

    def test_each_newline_starts_a_new_line(self):
        """Chaque retour a la ligne ouvre une ligne de plus."""
        assert _line_count("a\nb\nc") == 3

    def test_trailing_newline_counts_the_empty_last_line(self):
        """Un retour a la ligne final compte la ligne vide qui le suit."""
        # "a\nb\n" has 3 lines (a, b, empty after last \n)
        assert _line_count("a\nb\n") == 3


# ---------------------------------------------------------------------------
# Tests: wrap_snippetable threshold
# ---------------------------------------------------------------------------

class TestWrapSnippetableThreshold:
    def test_small_content_not_wrapped(self):
        """Content with fewer than SNIPPET_MIN_LINES should NOT be wrapped."""
        content = _make_content(10)
        result = wrap_snippetable(content, "tool123")
        assert "A SNIPPETER" not in result
        assert result == content

    def test_exactly_threshold_is_wrapped(self):
        """Content with exactly SNIPPET_MIN_LINES lines SHOULD be wrapped."""
        content = _make_content(SNIPPET_MIN_LINES)
        result = wrap_snippetable(content, "tool123")
        assert _SNIPPET_OPEN.format(tool_id="tool123") in result
        assert _SNIPPET_CLOSE in result

    def test_large_content_wrapped(self):
        """Content with more than SNIPPET_MIN_LINES lines SHOULD be wrapped."""
        content = _make_content(100)
        result = wrap_snippetable(content, "tool123")
        assert _SNIPPET_OPEN.format(tool_id="tool123") in result

    def test_empty_result_is_left_untouched(self):
        """Un resultat vide n'est jamais marque a snippeter."""
        result = wrap_snippetable("", "tool123")
        assert result == ""
        assert "A SNIPPETER" not in result


# ---------------------------------------------------------------------------
# Tests: wrap_file_snippetable threshold
# ---------------------------------------------------------------------------

class TestWrapFileSnippetableThreshold:
    def test_small_file_result_is_not_marked(self):
        """Un extrait de fichier court repart tel quel, sans marqueur."""
        content = _make_content(10)
        result = wrap_file_snippetable(content, "/some/path.py")
        assert "A SNIPPETER" not in result
        assert result == content

    def test_file_result_at_the_threshold_is_marked(self):
        """Pile au seuil, le resultat de fichier est marque a snippeter."""
        content = _make_content(SNIPPET_MIN_LINES)
        result = wrap_file_snippetable(content, "/some/path.py")
        assert _FILE_SNIPPET_OPEN.format(file_path="/some/path.py") in result
        assert _SNIPPET_CLOSE in result

    def test_long_file_result_is_marked(self):
        """Un long extrait de fichier est marque a snippeter."""
        content = _make_content(100)
        result = wrap_file_snippetable(content, "/some/path.py")
        assert _FILE_SNIPPET_OPEN.format(file_path="/some/path.py") in result


# ---------------------------------------------------------------------------
# Tests: get_unsnippeted_reads respects threshold
# ---------------------------------------------------------------------------

class TestGetUnsnippetedReadsThreshold:
    """get_unsnippeted_reads should ignore results below SNIPPET_MIN_LINES."""

    def _make_messages(self, content_lines: int):
        """Build a minimal message sequence: assistant Read -> tool result -> assistant (no snippet)."""
        content = _make_content(content_lines)
        return [
            {"role": "user", "content": "do something"},
            {
                "role": "assistant",
                "tool_calls": [
                    {"id": "r1", "name": "Read", "input": {"file_path": "/foo.py"}},
                    {"id": "m1", "name": "Methodology", "input": {"content": "x"}},
                ],
            },
            {"role": "tool", "tool_call_id": "r1", "name": "Read", "content": content},
            {"role": "tool", "tool_call_id": "m1", "name": "Methodology", "content": "ok"},
            # Subsequent assistant without Snippet
            {
                "role": "assistant",
                "tool_calls": [
                    {"id": "m2", "name": "Methodology", "input": {"content": "y"}},
                ],
            },
        ]

    def test_short_read_is_not_chased_for_a_snippet(self):
        """Une lecture courte ne reclame aucun Snippet."""
        from bouzecode.backend.tools.enforcement_hooks import get_unsnippeted_reads
        messages = self._make_messages(10)
        result = get_unsnippeted_reads(messages)
        assert result == []

    def test_long_read_is_reported_with_its_line_count(self):
        """Une lecture longue est signalee, avec son chemin et son nombre de lignes."""
        from bouzecode.backend.tools.enforcement_hooks import get_unsnippeted_reads
        messages = self._make_messages(100)
        result = get_unsnippeted_reads(messages)
        assert len(result) == 1
        assert result[0]["key"] == "/foo.py"
        assert result[0]["line_count"] == 100

    def test_read_at_the_threshold_is_reported(self):
        """Pile au seuil, la lecture est deja consideree comme a snippeter."""
        from bouzecode.backend.tools.enforcement_hooks import get_unsnippeted_reads
        messages = self._make_messages(SNIPPET_MIN_LINES)
        result = get_unsnippeted_reads(messages)
        assert len(result) == 1


# ---------------------------------------------------------------------------
# Tests: snippetable_results respects threshold
# ---------------------------------------------------------------------------

class TestSnippetableResultsThreshold:
    """enforcement_call.snippetable_results should exclude small results."""

    def _make_messages(self, content_lines: int):
        content = _make_content(content_lines)
        return [
            {"role": "user", "content": "hi"},
            {
                "role": "assistant",
                "tool_calls": [
                    {"id": "r1", "name": "Read", "input": {"file_path": "/bar.py"}},
                ],
            },
            {"role": "tool", "tool_call_id": "r1", "name": "Read", "content": content},
        ]

    def test_short_read_is_not_offered_to_the_recovery(self):
        """Une lecture courte n'est pas proposee au rattrapage de Snippet."""
        from bouzecode.backend.agent.enforcement_call import snippetable_results
        messages = self._make_messages(10)
        result = snippetable_results(messages)
        assert result == []

    def test_long_read_is_offered_to_the_recovery(self):
        """Une lecture longue est proposee au rattrapage, avec son chemin."""
        from bouzecode.backend.agent.enforcement_call import snippetable_results
        messages = self._make_messages(100)
        result = snippetable_results(messages)
        assert len(result) == 1
        assert result[0]["file_path"] == "/bar.py"
