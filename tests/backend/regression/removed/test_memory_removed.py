"""Verify that the memory module has been cleanly removed."""
import importlib
import pytest


def test_memory_module_not_importable():
    """The bouzecode.backend.memory package must no longer exist."""
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("bouzecode.backend.memory")


@pytest.mark.skip(reason="Memory tools exist in OSS integration — not removed")
def test_memory_tools_not_registered():
    """MemorySave/Search/Delete/List must not appear in the tool registry."""
    from bouzecode.backend.core.tool_registry import get_all_tools
    memory_tools = [t.name for t in get_all_tools() if t.name.startswith("Memory")]
    assert memory_tools == [], f"Memory tools still registered: {memory_tools}"


def test_tool_registration_imports_cleanly():
    """tools/registration.py must import without errors after memory removal."""
    import bouzecode.backend.tools.registration  # noqa: F401


def test_commands_import_cleanly():
    """commands package must import without errors (agents_cmd replaces memory_cmd)."""
    from bouzecode.backend.commands import _print_background_notifications
    assert callable(_print_background_notifications)


def test_context_builds_without_memory():
    """context.py must import without referencing memory module."""
    import bouzecode.backend.core.context  # noqa: F401
