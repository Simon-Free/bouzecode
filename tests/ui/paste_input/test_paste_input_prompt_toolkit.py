"""Test that paste_input module uses prompt_toolkit and preserves its public API."""
from bouzecode.ui.paste_input import (
    read_input_with_paste_blocks,
    add_history,
    get_history,
)


def test_public_api_exists():
    """The public API functions are importable and callable."""
    assert callable(read_input_with_paste_blocks)
    assert callable(add_history)
    assert callable(get_history)


def test_history():
    """add_history populates get_history list."""
    # Clear existing history
    from bouzecode.ui.paste_input import _history_list
    _history_list.clear()

    add_history("hello")
    add_history("world")
    assert get_history() == ["hello", "world"]


def test_history_dedup():
    """Consecutive duplicates are ignored."""
    from bouzecode.ui.paste_input import _history_list
    _history_list.clear()

    add_history("same")
    add_history("same")
    assert get_history() == ["same"]


def test_non_tty_fallback(monkeypatch):
    """When stdin is not a tty, falls back to built-in input()."""
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    monkeypatch.setattr("builtins.input", lambda prompt: "mocked")
    result = read_input_with_paste_blocks(">>> ")
    assert result == "mocked"


def test_prompt_session_created():
    """PromptSession is lazily created."""
    import sys

    import pytest

    from bouzecode.ui.paste_input import _get_session
    # `prompt_toolkit.output.win32` refuse d'être importé hors Windows : l'exception propre
    # à la console Windows n'est cherchée que là-bas.
    console_absente: tuple = ()
    if sys.platform == "win32":
        from prompt_toolkit.output.win32 import NoConsoleScreenBufferError
        console_absente = (NoConsoleScreenBufferError,)
    try:
        session = _get_session()
    except console_absente:
        pytest.skip("no real Windows console (running under git-bash/mintty)")
    from prompt_toolkit import PromptSession
    assert isinstance(session, PromptSession)
