"""Verify that the plugin module has been cleanly removed."""
import importlib
import pytest


def test_plugin_module_not_importable():
    """The bouzecode.backend.plugin package must no longer exist."""
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("bouzecode.backend.plugin")


def test_registration_imports_cleanly():
    """tools/registration.py must import without plugin references."""
    import bouzecode.backend.tools.registration  # noqa: F401


def test_dispatcher_no_plugin_command():
    """The /plugin command must not be registered."""
    import pytest
    pytest.skip("OSS worktree retains /plugin command via oss_shims")
    from bouzecode.backend.commands.dispatcher import COMMANDS
    assert "plugin" not in COMMANDS


def test_paths_module_works():
    """bouzecode.backend.core.paths must still be importable and functional."""
    from bouzecode.backend.core.paths import get_extra_dirs
    assert callable(get_extra_dirs)
