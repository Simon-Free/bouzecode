"""Test that repl.py has valid Python syntax (reproduces IndentationError bug)."""
import py_compile
import pathlib


def test_repl_compiles():
    """repl.py must be valid Python — py_compile raises on syntax errors."""
    repl_path = pathlib.Path(__file__).resolve().parents[4] / "src" / "bouzecode" / "ui" / "repl.py"
    # This will raise py_compile.PyCompileError if there's a SyntaxError
    py_compile.compile(str(repl_path), doraise=True)
