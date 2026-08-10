"""Verify that the mcp module has been cleanly removed."""
import importlib
import pytest


def test_mcp_module_not_importable():
    """The bouzecode.backend.mcp package must no longer exist."""
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("bouzecode.backend.mcp")


def test_registration_imports_cleanly():
    """tools/registration.py must import without mcp references."""
    import bouzecode.backend.tools.registration  # noqa: F401


@pytest.mark.skip(reason="OSS worktree has /mcp via oss_shims (intentional)")
def test_dispatcher_no_mcp_command():
    """The /mcp command must not be registered."""
    from bouzecode.backend.commands.dispatcher import COMMANDS
    assert "mcp" not in COMMANDS


def test_skills_cmd_still_works():
    """cmd_skills must still be importable from skills_mcp module."""
    from bouzecode.backend.commands.extensions.skills_mcp import cmd_skills
    assert callable(cmd_skills)
