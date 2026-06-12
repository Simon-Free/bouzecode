# [desc] <tool_use name="FinalAnswer" id="f1"><param name="answer">E2E tests for backend folder_desc tool: listing, error handling, depth filtering, and symbol extraction.</param></tool_use> [/desc]
"""E2E test for backend folder_desc tool on a temporary directory.

All test files include [desc] tags so no LLM analysis is triggered.
"""
import sys
from pathlib import Path

import pytest


def test_folder_desc_basic(tmp_path):
    """_get_folder_description lists files with their [desc] tags."""
    # Create a small project structure with [desc] tags
    (tmp_path / "main.py").write_text(
        '# [desc] Entry point for the application. [/desc]\n'
        'def main():\n'
        '    print("hello")\n',
        encoding="utf-8",
    )
    (tmp_path / "utils.py").write_text(
        '# [desc] Utility helpers for string processing. [/desc]\n'
        'def strip(s):\n'
        '    return s.strip()\n',
        encoding="utf-8",
    )
    sub = tmp_path / "lib"
    sub.mkdir()
    (sub / "core.py").write_text(
        '# [desc] Core logic module. [/desc]\n'
        'class Engine:\n'
        '    pass\n',
        encoding="utf-8",
    )

    from bouzecode.backend.tools.folder_desc.tools import _get_folder_description

    result = _get_folder_description(
        {"folder_path": str(tmp_path), "max_depth": 2},
        config={},
    )

    # Should list the folder name and all 3 files with descriptions
    assert tmp_path.name in result
    assert "main.py" in result
    assert "Entry point for the application" in result
    assert "utils.py" in result
    assert "Utility helpers" in result
    assert "core.py" in result
    assert "Core logic module" in result


def test_folder_desc_not_a_directory(tmp_path):
    """Returns error message for non-existent directory."""
    from bouzecode.backend.tools.folder_desc.tools import _get_folder_description

    result = _get_folder_description(
        {"folder_path": str(tmp_path / "nonexistent")},
        config={},
    )
    assert "Error" in result
    assert "not a directory" in result


def test_folder_desc_no_code_files(tmp_path):
    """Returns appropriate message when no code files found."""
    # Create only a .txt file (not in EXT_TO_STYLE)
    (tmp_path / "readme.txt").write_text("Hello", encoding="utf-8")

    from bouzecode.backend.tools.folder_desc.tools import _get_folder_description

    result = _get_folder_description(
        {"folder_path": str(tmp_path)},
        config={},
    )
    assert "No code files" in result


def test_folder_desc_max_depth_filtering(tmp_path):
    """Files deeper than max_depth are excluded with a note."""
    (tmp_path / "top.py").write_text(
        '# [desc] Top level. [/desc]\nx = 1\n', encoding="utf-8"
    )
    deep = tmp_path / "a" / "b" / "c"
    deep.mkdir(parents=True)
    (deep / "deep.py").write_text(
        '# [desc] Deep file. [/desc]\ny = 2\n', encoding="utf-8"
    )

    from bouzecode.backend.tools.folder_desc.tools import _get_folder_description

    result = _get_folder_description(
        {"folder_path": str(tmp_path), "max_depth": 1},
        config={},
    )

    assert "top.py" in result
    assert "Top level" in result
    # deep.py is at depth 3 (a/b/c/deep.py) so excluded
    assert "deep.py" not in result
    assert "not shown" in result


def test_folder_desc_symbols_extracted(tmp_path):
    """Symbols (functions, classes) are extracted from Python files."""
    (tmp_path / "module.py").write_text(
        '# [desc] A module with symbols. [/desc]\n'
        '\n'
        'def helper():\n'
        '    """Helps with things."""\n'
        '    pass\n'
        '\n'
        'class Service:\n'
        '    """Main service class."""\n'
        '    def run(self):\n'
        '        """Run the service."""\n'
        '        pass\n',
        encoding="utf-8",
    )

    from bouzecode.backend.tools.folder_desc.tools import _get_folder_description

    result = _get_folder_description(
        {"folder_path": str(tmp_path), "max_depth": 2},
        config={},
    )

    assert "module.py" in result
    assert "helper" in result
    assert "Service" in result
    assert "Helps with things" in result


def test_flat_folder_desc_importable():
    """The flat folder_desc/ package remains importable for backward compat."""
    # This just verifies the flat package structure is intact
    import folder_desc
    assert hasattr(folder_desc, "__file__") or hasattr(folder_desc, "__path__")
