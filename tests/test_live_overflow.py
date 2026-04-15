# [desc] Tests for collapsed diff display, compact +N/-M counts, /diff command, and Rich Live overflow handling. [/desc]
"""Tests for Rich Live overflow fix, collapsed diff display, and /diff command."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import MagicMock, patch, call
import ui.rendering as cc
import ui.tool_display as _td
from commands.misc import cmd_diff as _cmd_diff
cc.print_tool_end = _td.print_tool_end
cc.cmd_diff = _cmd_diff
cc._last_diffs = _td._last_diffs


def _reset_streaming_state():
    """Reset all module-level streaming globals to a clean state."""
    cc._accumulated_text.clear()
    cc._current_live = None
    cc._live_overflow = False
    cc._overflow_lines_buf.clear()
    cc._last_diffs.clear()


# ── Bug 1: Diffs collapsed by default in print_tool_end ──────────────────

class TestDiffCollapsed:
    """print_tool_end() should NOT call render_diff — only show file summary."""

    def setup_method(self):
        _reset_streaming_state()

    def test_edit_result_no_diff_rendered(self, capsys):
        result = "File updated — test.py\n\n--- a/test.py\n+++ b/test.py\n@@ -1 +1 @@\n-old\n+new"
        cc.print_tool_end("Edit", result, verbose=False)
        out = capsys.readouterr().out
        assert "File updated" in out
        assert "--- a/test.py" not in out
        assert "+++ b/test.py" not in out
        assert "-old" not in out

    def test_write_result_no_diff_rendered(self, capsys):
        result = "File created — hello.py\n\n--- a/hello.py\n+++ b/hello.py\n@@ -0,0 +1 @@\n+print('hi')"
        cc.print_tool_end("Write", result, verbose=False)
        out = capsys.readouterr().out
        assert "File created" in out
        assert "+print" not in out

    def test_non_diff_result_unaffected(self, capsys):
        result = "Some normal tool output\nwith multiple lines"
        cc.print_tool_end("Bash", result, verbose=False)
        out = capsys.readouterr().out
        assert "2 lines" in out

    def test_error_result_shown(self, capsys):
        result = "Error: file not found"
        cc.print_tool_end("Edit", result, verbose=False)
        out = capsys.readouterr().out
        assert "Error" in out


# ── Compact +N/-M format and _last_diffs storage ──────────────────────────

class TestDiffCompactFormat:
    """print_tool_end() should show +N/-M counts and store diffs in _last_diffs."""

    def setup_method(self):
        _reset_streaming_state()

    def test_edit_shows_change_counts(self, capsys):
        result = "File updated — test.py\n\n--- a/test.py\n+++ b/test.py\n@@ -1,2 +1,3 @@\n-old\n+new\n+extra"
        cc.print_tool_end("Edit", result, verbose=False)
        out = capsys.readouterr().out
        assert "+2" in out
        assert "-1" in out

    def test_diff_stored_in_last_diffs(self):
        result = "File updated — test.py\n\n--- a/test.py\n+++ b/test.py\n@@ -1 +1 @@\n-old\n+new"
        cc.print_tool_end("Edit", result, verbose=False)
        assert "test.py" in cc._last_diffs
        assert "+new" in cc._last_diffs["test.py"]

    def test_diff_hint_shown(self, capsys):
        result = "File updated — test.py\n\n--- a/test.py\n+++ b/test.py\n@@ -1 +1 @@\n-old\n+new"
        cc.print_tool_end("Edit", result, verbose=False)
        out = capsys.readouterr().out
        assert "/diff" in out

    def test_multiple_diffs_stored(self):
        r1 = "File updated — a.py\n\n--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-x\n+y"
        r2 = "File updated — b.py\n\n--- a/b.py\n+++ b/b.py\n@@ -1 +1 @@\n-p\n+q"
        cc.print_tool_end("Edit", r1, verbose=False)
        cc.print_tool_end("Edit", r2, verbose=False)
        assert "a.py" in cc._last_diffs
        assert "b.py" in cc._last_diffs


# ── /diff command ─────────────────────────────────────────────────────────

class TestDiffCommand:
    """The /diff slash command should list and display stored diffs."""

    def setup_method(self):
        _reset_streaming_state()

    def test_diff_no_diffs_stored(self, capsys):
        cc.cmd_diff("", MagicMock(), {})
        out = capsys.readouterr().out
        assert "No diffs" in out

    def test_diff_lists_summary(self, capsys):
        """No args → summary listing with +N/-M counts (not full diff)."""
        cc._last_diffs["src/app.py"] = "--- a/src/app.py\n+++ b/src/app.py\n@@ -1 +1 @@\n-old\n+new"
        cc.cmd_diff("", MagicMock(), {})
        out = capsys.readouterr().out
        assert "src/app.py" in out
        assert "+1/-1" in out

    def test_diff_shows_specific_file(self, capsys):
        """Providing exact path renders the full diff."""
        cc._last_diffs["bar.py"] = "--- a/bar.py\n+++ b/bar.py\n@@ -1 +1 @@\n-old\n+new_bar"
        cc.cmd_diff("bar.py", MagicMock(), {})
        out = capsys.readouterr().out
        assert "+new_bar" in out

    def test_diff_filter_excludes_others(self, capsys):
        cc._last_diffs["foo.py"] = "-old\n+new_foo"
        cc._last_diffs["bar.py"] = "-old\n+new_bar"
        cc.cmd_diff("bar.py", MagicMock(), {})
        out = capsys.readouterr().out
        assert "+new_bar" in out
        assert "foo" not in out

    def test_diff_not_found(self, capsys):
        cc._last_diffs["test.py"] = "some diff"
        cc.cmd_diff("nonexistent", MagicMock(), {})
        captured = capsys.readouterr()
        assert "No diff found" in captured.err


# ── Bug 2: Rich Live overflow → text repetition ─────────────────────────

class TestStreamOverflow:
    """stream_text() should stop Live and switch to direct print when content
    exceeds ~60% of terminal height, preventing cascading repetition."""

    def setup_method(self):
        _reset_streaming_state()

    def teardown_method(self):
        _reset_streaming_state()

    def test_short_text_no_overflow(self):
        """Text shorter than terminal should NOT trigger overflow."""
        mock_live = MagicMock()
        cc._current_live = mock_live
        with patch.object(cc, 'console', MagicMock(height=40, width=80)):
            cc.stream_text("short line\n")
        assert cc._live_overflow is False
        assert cc._current_live is mock_live
        mock_live.update.assert_called()
        mock_live.stop.assert_not_called()

    def test_overflow_stops_live(self):
        """When accumulated text exceeds 60% of terminal height, Live must stop."""
        mock_live = MagicMock()
        cc._current_live = mock_live
        with patch.object(cc, 'console', MagicMock(height=10, width=80)):
            for i in range(10):
                cc.stream_text(f"line {i}\n")
        assert cc._live_overflow is True
        assert cc._current_live is None
        mock_live.stop.assert_called_once()

    def test_overflow_clears_live_before_stop(self):
        """On overflow, update('') must be called before stop() to clear the frame."""
        mock_live = MagicMock()
        cc._current_live = mock_live
        call_order = []
        mock_live.update.side_effect = lambda *a, **kw: call_order.append(("update", a))
        mock_live.stop.side_effect = lambda *a, **kw: call_order.append(("stop",))
        with patch.object(cc, 'console', MagicMock(height=10, width=80)):
            for i in range(10):
                cc.stream_text(f"line {i}\n")
        stop_idx = next(i for i, c in enumerate(call_order) if c[0] == "stop")
        clear_call = call_order[stop_idx - 1]
        assert clear_call[0] == "update"
        assert clear_call[1][0] == ""  # first positional arg is ""

    def test_overflow_stays_direct_after_trigger(self):
        """After overflow triggers, subsequent chunks use overflow Rich rendering."""
        mock_live = MagicMock()
        cc._current_live = mock_live
        mock_console = MagicMock(height=10, width=80)
        with patch.object(cc, 'console', mock_console):
            for i in range(10):
                cc.stream_text(f"line {i}\n")
            cc.stream_text("extra chunk\n")
            cc.stream_text("another chunk\n")
        assert cc._current_live is None
        assert cc._live_overflow is True

    def test_flush_resets_overflow_flag(self):
        """flush_response() must reset _live_overflow to False."""
        cc._live_overflow = True
        cc._accumulated_text.append("some text")
        cc.flush_response()
        assert cc._live_overflow is False
        assert len(cc._accumulated_text) == 0

    def test_flush_after_overflow_renders_remaining(self):
        """When overflow happened, flush_response() renders remaining buffered line via Rich."""
        cc._live_overflow = True
        cc._overflow_lines_buf.append("# Hello **world**")
        cc._accumulated_text.append("# Hello **world**\n")
        with patch.object(cc, 'console') as mock_console:
            cc.flush_response()
        mock_console.print.assert_called_once()
        assert cc._live_overflow is False
        assert len(cc._overflow_lines_buf) == 0

    def test_flush_normal_live_stops_it(self):
        """Normal case: flush_response() stops active Live."""
        mock_live = MagicMock()
        cc._current_live = mock_live
        cc._accumulated_text.append("text")
        cc.flush_response()
        mock_live.stop.assert_called_once()
        assert cc._current_live is None

    def test_tall_text_before_live_starts_goes_direct(self):
        """If text is already too tall when first chunk arrives, skip Live entirely."""
        big_text = "\n".join(f"line{i}" for i in range(50))
        mock_console = MagicMock(height=10, width=80)
        with patch.object(cc, 'console', mock_console):
            cc.stream_text(big_text)
        assert cc._live_overflow is True
        assert cc._current_live is None

    def test_threshold_is_sixty_percent(self):
        """Threshold should be 60% of terminal height."""
        mock_live = MagicMock()
        cc._current_live = mock_live
        # height=20, width=80 -> threshold = 12
        # 11 lines should NOT overflow
        with patch.object(cc, 'console', MagicMock(height=20, width=80)):
            for i in range(11):
                cc.stream_text(f"line {i}\n")
        assert cc._live_overflow is False
        # 2 more -> 13 lines, exceeds 12
        with patch.object(cc, 'console', MagicMock(height=20, width=80)):
            cc.stream_text("line 11\n")
            cc.stream_text("line 12\n")
        assert cc._live_overflow is True


# ── Height estimation ────────────────────────────────────────────────────

class TestHeightEstimation:
    """_estimate_rendered_lines should account for word-wrap."""

    def test_short_lines(self):
        assert cc._estimate_rendered_lines("hello\nworld", 80) == 2

    def test_long_line_wraps(self):
        assert cc._estimate_rendered_lines("a" * 160, 80) == 2

    def test_empty_string(self):
        assert cc._estimate_rendered_lines("", 80) == 1

    def test_mixed_lengths(self):
        # "short" (1) + "a"*200 (3 at width 80) + "end" (1) = 5
        text = "short\n" + "a" * 200 + "\nend"
        assert cc._estimate_rendered_lines(text, 80) == 5
