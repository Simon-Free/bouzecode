"""Test that brainstorm module is fully removed and doesn't break imports."""
import importlib
import pytest


def test_no_brainstorm_importable():
    """brainstorm module must not be importable from either old or new location."""
    for mod in [
        "bouzecode.backend.commands.brainstorm",
        "bouzecode.backend.commands.brainstorm",
    ]:
        with pytest.raises((ImportError, ModuleNotFoundError)):
            importlib.import_module(mod)


def test_embedded_data_no_brainstorm_attrs():
    """_embedded_data should not export BRAINSTORM_PERSONA_TEMPLATE or PERSONA_GENERATION_SYSTEM."""
    from bouzecode.backend.core import _embedded_data
    assert not hasattr(_embedded_data, "BRAINSTORM_PERSONA_TEMPLATE")
    assert not hasattr(_embedded_data, "PERSONA_GENERATION_SYSTEM")


def test_repl_sentinels_importable():
    """repl_sentinels should import without error (no dangling brainstorm ref)."""
    import bouzecode.ui.repl_sentinels  # noqa: F401


def test_package_importable():
    """Top-level bouzecode package must import cleanly."""
    import bouzecode  # noqa: F401
