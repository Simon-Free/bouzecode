# [desc] Smoke tests verifying bouzecode package and submodules are importable after src/ migration [/desc]
"""Smoke tests verifying the package is importable after src/ migration."""


def test_import_bouzecode_package():
    import bouzecode
    assert hasattr(bouzecode, 'main')
    assert callable(bouzecode.main)


def test_import_core_submodules():
    from bouzecode.backend.core.config import CONFIG_DIR
    from bouzecode.backend.core import tool_registry
    assert hasattr(tool_registry, 'register_tool')
    assert CONFIG_DIR is not None


def test_import_subpackages():
    from bouzecode.backend.commands.session import revert_cmd
    from bouzecode.backend.checkpoint import store
    assert revert_cmd is not None
    assert store is not None
