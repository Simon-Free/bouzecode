# [desc] Tests that symbol-not-found errors in file_ops._read list available symbols for the user [/desc]
"""Test that symbol-not-found error includes available symbols."""
import tempfile
from pathlib import Path
from bouzecode.backend.tools.ops.file_ops import _read


def test_symbol_not_found_serves_the_file_and_lists_available():
    """Symbole absent : le fichier est servi dans le même tour, avec la liste des
    symboles réellement présents pour cibler le Read suivant."""
    code = '''\
def hello():
    pass

class Config:
    def load(self):
        pass

    def save(self):
        pass

def goodbye():
    pass
'''
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(code)
        f.flush()
        path = f.name

    try:
        result = _read(path, symbol="nonexistent")
        assert "symbol 'nonexistent' not found" in result, "l'absence doit rester dite"
        assert "Available symbols:" in result
        assert "hello" in result
        assert "Config" in result
        assert "Config.load" in result
        assert "Config.save" in result
        assert "goodbye" in result
        # Ce qui a changé : plus de refus, le fichier arrive avec la réponse.
        assert "def hello():" in result and "def goodbye():" in result
        assert result.rstrip().endswith("    pass"), "le fichier est servi jusqu'au bout"
    finally:
        Path(path).unlink()


def test_symbol_found_still_works():
    """Ensure normal symbol reading still works."""
    code = '''\
def hello():
    return "world"
'''
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(code)
        f.flush()
        path = f.name

    try:
        result = _read(path, symbol="hello")
        assert "def hello" in result
        assert "world" in result
    finally:
        Path(path).unlink()
