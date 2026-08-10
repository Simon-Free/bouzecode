"""Test that session_load module can be imported without errors."""


def test_session_load_import():
    """Reproduce bug: import of ContextState fails in session_load."""
    from bouzecode.backend.commands.session.session_load import cmd_load  # noqa: F401
