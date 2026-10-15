# [desc] Tests que safe_print/_safe_live_update dégradent en texte brut si pygments casse, sans tuer le tour [/desc]
"""Regression: `ClassNotFound: Could not find style module 'pygments.styles.default'`.

Rich resolves the syntax theme through `pygments.styles.get_style_by_name()` at PRINT
time, so a broken/partial pygments install raises from inside display code. Before the
fix that surfaced as "Turn aborted due to an unhandled error" — the whole turn died
because a colour theme was missing. These tests pin the degraded-but-alive behaviour.
"""
import pytest

from bouzecode.ui import rendering, tool_display


class _ExplodingConsole:
    """Stands in for a rich Console whose render pipeline hits a broken pygments."""

    def __init__(self):
        self.calls = 0

    def print(self, *args, **kwargs):
        self.calls += 1
        raise Exception(
            "ClassNotFound: Could not find style module 'pygments.styles.default', "
            "though it should be builtin."
        )


def test_safe_print_falls_back_to_plain_text(monkeypatch, capsys):
    boom = _ExplodingConsole()
    monkeypatch.setattr(rendering, "console", boom)

    rendering.safe_print(object(), "hello **world**")

    assert boom.calls == 1
    assert "hello **world**" in capsys.readouterr().out


def test_safe_print_without_rich_still_prints(monkeypatch, capsys):
    monkeypatch.setattr(rendering, "console", None)

    rendering.safe_print(object(), "plain payload")

    assert "plain payload" in capsys.readouterr().out


def test_final_answer_survives_broken_theme(monkeypatch, capsys):
    """The critical path: FinalAnswer is rendered as Markdown at session close."""
    # This case forces the rich branch of `_print_final_answer`, so rich must be
    # importable (its names are bound under a `try: from rich ... except ImportError`).
    pytest.importorskip("rich")
    monkeypatch.setattr(rendering, "console", _ExplodingConsole())
    monkeypatch.setattr(tool_display, "_RICH_CONSOLE", _ExplodingConsole(), raising=False)

    tool_display._print_final_answer("# Done\n\n```python\nprint(1)\n```")

    out = capsys.readouterr().out
    assert "Done" in out
    assert "print(1)" in out


def test_live_update_failure_disables_rich_and_keeps_text(monkeypatch, capsys):
    class _ExplodingLive:
        def __init__(self):
            self.stopped = False

        def update(self, *a, **k):
            raise Exception("ClassNotFound: pygments.styles.default")

        def stop(self):
            self.stopped = True

    live = _ExplodingLive()
    monkeypatch.setattr(rendering, "_RICH_LIVE", True, raising=False)
    monkeypatch.setattr(rendering, "_current_live", live, raising=False)

    rendering._safe_live_update(live, object(), "streamed text")

    assert live.stopped is True
    assert rendering._RICH_LIVE is False
    assert rendering._current_live is None
    assert "streamed text" in capsys.readouterr().out
