# [desc] Tests that symbol-not-found errors list available symbols and that valid symbol reads still work
# <tool_use name="FinalAnswer" id="r1"><param name="answer">Tests that symbol-not-found errors list available symbols and that valid symbol reads still work</param></tool_use> [/desc]
"""Test that symbol-not-found error includes available symbols."""
import tempfile
from pathlib import Path
from bouzecode.backend.tools.ops.file_ops import _read


def test_symbol_not_found_lists_available():
    """When a symbol doesn't exist, the error should list available symbols."""
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
        assert "Error: symbol 'nonexistent' not found" in result
        assert "Available symbols:" in result
        assert "hello" in result
        assert "Config" in result
        assert "Config.load" in result
        assert "Config.save" in result
        assert "goodbye" in result
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
