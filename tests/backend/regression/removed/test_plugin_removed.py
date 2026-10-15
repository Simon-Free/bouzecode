"""Verify that the OLD legacy /plugin command and its wiring are gone.

A NEW plugin system (bouzecode.backend.plugin: store/loader/types) was added
intentionally and is unrelated to the removed legacy /plugin command — so we no
longer assert the package is unimportable, only that the old command is gone.
"""


def test_registration_imports_cleanly():
    """tools/registration.py must import without plugin references."""
    import bouzecode.backend.tools.registration  # noqa: F401


def test_dispatcher_no_plugin_command():
    """The /plugin command must not be registered."""
    from bouzecode.backend.commands.dispatcher import COMMANDS
    assert "plugin" not in COMMANDS


def test_paths_module_works():
    """bouzecode.backend.core.paths must still be importable and functional."""
    from bouzecode.backend.core.paths import get_extra_dirs
    assert callable(get_extra_dirs)
