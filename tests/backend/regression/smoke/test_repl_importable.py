"""Verify that ui/repl.py imports without errors."""
import importlib


def test_repl_module_importable():
    """bouzecode.ui.repl must be importable without ImportError."""
    mod = importlib.import_module("bouzecode.ui.repl")
    assert hasattr(mod, "repl"), "repl() function must exist"
