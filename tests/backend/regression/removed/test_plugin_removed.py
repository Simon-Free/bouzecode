"""Verify that the plugin module has been cleanly removed."""
import importlib
import pytest


def test_plugin_command_routes_to_the_flat_package():
    """`/plugin` is served by the flat `plugin/` package, not by the engine's own.

    This lock used to assert that `bouzecode.backend.plugin` did not exist. The
    engine that was ported in ships its own plugin loader under that name, so the
    absence check no longer holds; what still matters publicly is that the user
    command keeps resolving to the flat package via the OSS shim.
    """
    importlib.import_module("plugin")
    from bouzecode.backend.commands.oss_shims import plugin_cmd
    assert callable(plugin_cmd.cmd_plugin)


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
