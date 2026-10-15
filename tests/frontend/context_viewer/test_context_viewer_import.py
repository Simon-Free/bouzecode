# [desc] Tests that context_viewer builder module imports and _load_turn_dumps handles missing sessions [/desc]
"""Test that context_viewer builder module can be imported without ModuleNotFoundError."""


def test_builder_import():
    """Importing builder should not raise ModuleNotFoundError on ...config."""
    from bouzecode.web_v2.runtime.context_viewer.builder import extract_per_call_data  # noqa: F401


def test_load_turn_dumps_import():
    """_load_turn_dumps triggers the lazy import of CONFIG_DIR - must not crash."""
    from bouzecode.web_v2.runtime.context_viewer.builder import _load_turn_dumps

    # Call with empty string — should return {} without crashing
    result = _load_turn_dumps("")
    assert result == {}


def test_load_turn_dumps_with_fake_session():
    """Calling _load_turn_dumps with a non-existent session returns empty dict."""
    from bouzecode.web_v2.runtime.context_viewer.builder import _load_turn_dumps

    result = _load_turn_dumps("nonexistent_session_id_12345")
    assert result == {}
