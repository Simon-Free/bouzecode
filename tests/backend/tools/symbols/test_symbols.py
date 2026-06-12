# [desc] Tests Python symbol extraction, lookup, and integration with file read and folder description tools. [/desc]
from bouzecode.backend.tools.folder_desc.symbols import extract_symbols, find_symbol


def test_extract_python_function(tmp_path):
    f = tmp_path / "mod.py"
    f.write_text("def hello():\n    \"\"\"Say hello.\"\"\"\n    pass\n")
    syms = extract_symbols(str(f))
    assert len(syms) == 1
    assert syms[0].name == "hello"
    assert syms[0].kind == "def"
    assert syms[0].docstring == "Say hello."
    assert syms[0].start_line == 1
    assert syms[0].end_line == 3


def test_extract_python_class_with_methods(tmp_path):
    f = tmp_path / "cls.py"
    f.write_text(
        "class Config:\n"
        "    \"\"\"Configuration container.\"\"\"\n"
        "    def load(self):\n"
        "        \"\"\"Load from file.\"\"\"\n"
        "        pass\n"
        "    def save(self):\n"
        "        pass\n"
    )
    syms = extract_symbols(str(f))
    assert len(syms) == 1
    cls = syms[0]
    assert cls.name == "Config"
    assert cls.kind == "class"
    assert cls.docstring == "Configuration container."
    assert len(cls.children) == 2
    assert cls.children[0].name == "load"
    assert cls.children[0].docstring == "Load from file."
    assert cls.children[1].name == "save"
    assert cls.children[1].docstring is None


def test_extract_python_async(tmp_path):
    f = tmp_path / "async_mod.py"
    f.write_text("async def fetch():\n    \"\"\"Fetch data.\"\"\"\n    pass\n")
    syms = extract_symbols(str(f))
    assert len(syms) == 1
    assert syms[0].name == "fetch"
    assert syms[0].kind == "def"


def test_extract_python_syntax_error(tmp_path):
    f = tmp_path / "bad.py"
    f.write_text("def broken(\n")
    assert extract_symbols(str(f)) == []


def test_extract_unsupported_ext(tmp_path):
    f = tmp_path / "mod.rb"
    f.write_text("def hello\n  puts 'hi'\nend\n")
    assert extract_symbols(str(f)) == []


def test_find_symbol_toplevel(tmp_path):
    f = tmp_path / "mod.py"
    f.write_text("x = 1\ndef foo():\n    pass\ndef bar():\n    pass\n")
    assert find_symbol(str(f), "foo") == (2, 3)
    assert find_symbol(str(f), "bar") == (4, 5)


def test_find_symbol_nested(tmp_path):
    f = tmp_path / "mod.py"
    f.write_text(
        "class Svc:\n"
        "    def run(self):\n"
        "        pass\n"
        "    def stop(self):\n"
        "        pass\n"
    )
    assert find_symbol(str(f), "Svc.run") == (2, 3)
    assert find_symbol(str(f), "Svc.stop") == (4, 5)
    assert find_symbol(str(f), "Svc") == (1, 5)


def test_find_symbol_not_found(tmp_path):
    f = tmp_path / "mod.py"
    f.write_text("x = 1\n")
    assert find_symbol(str(f), "missing") is None


def test_read_with_symbol(tmp_path):
    f = tmp_path / "mod.py"
    f.write_text(
        "import os\n"
        "\n"
        "def main():\n"
        "    \"\"\"Entry point.\"\"\"\n"
        "    print('hi')\n"
        "\n"
        "def other():\n"
        "    pass\n"
    )
    from bouzecode.backend.tools.ops.file_ops import _read
    result = _read(str(f), symbol="main")
    assert "def main" in result
    assert "Entry point" in result
    assert "def other" not in result
    assert "     3\t" in result
    assert "     5\t" in result


def test_read_symbol_not_found(tmp_path):
    f = tmp_path / "mod.py"
    f.write_text("x = 1\n")
    from bouzecode.backend.tools.ops.file_ops import _read
    result = _read(str(f), symbol="missing")
    assert "Error" in result
    assert "missing" in result


def test_folder_description_shows_symbols(tmp_path):
    f = tmp_path / "app.py"
    f.write_text(
        "# [desc] Main app [/desc]\n"
        "def run():\n"
        "    \"\"\"Start the app.\"\"\"\n"
        "    pass\n"
        "class Server:\n"
        "    \"\"\"HTTP server.\"\"\"\n"
        "    def listen(self):\n"
        "        pass\n"
    )
    from bouzecode.backend.tools.folder_desc.tools import _get_folder_description
    result = _get_folder_description({"folder_path": str(tmp_path)}, {})
    assert "Main app" in result
    assert "def run()" in result
    assert "Start the app" in result
    assert "class Server" in result
    assert "def listen()" in result
    assert "[L" in result
