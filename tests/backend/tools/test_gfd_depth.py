# [desc] Tests GetFolderDescription max_depth parameter filtering and truncation messages for nested directories.
# <tool_use name="FinalAnswer" id="r1"><param name="answer">Tests GetFolderDescription max_depth parameter filtering and truncation messages for nested directories.</param></tool_use> [/desc]
"""Test GetFolderDescription max_depth parameter."""

import tempfile
from pathlib import Path
from unittest.mock import patch

from bouzecode.backend.tools.folder_desc.tools import _get_folder_description


def _create_tree(root: Path):
    """Create a nested tree: root/a.py, root/sub/b.py, root/sub/deep/c.py, root/sub/deep/deeper/d.py"""
    (root / "a.py").write_text("# [desc] Top level file [/desc]\n", encoding="utf-8")
    (root / "sub").mkdir()
    (root / "sub" / "b.py").write_text("# [desc] Depth 1 file [/desc]\n", encoding="utf-8")
    (root / "sub" / "deep").mkdir()
    (root / "sub" / "deep" / "c.py").write_text("# [desc] Depth 2 file [/desc]\n", encoding="utf-8")
    (root / "sub" / "deep" / "deeper").mkdir()
    (root / "sub" / "deep" / "deeper" / "d.py").write_text("# [desc] Depth 3 file [/desc]\n", encoding="utf-8")


class TestGFDMaxDepth:
    """GetFolderDescription respects max_depth parameter."""

    def test_default_depth_2_excludes_deep_files(self, tmp_path):
        _create_tree(tmp_path)
        # Default max_depth=2: should show a.py (depth 0), b.py (depth 1), c.py (depth 2), NOT d.py (depth 3)
        result = _get_folder_description({"folder_path": str(tmp_path)}, {})
        assert "a.py" in result
        assert "b.py" in result
        assert "c.py" in result
        assert "d.py" not in result
        assert "not shown" in result.lower() or "deeper" not in result

    def test_explicit_depth_1_excludes_deeper(self, tmp_path):
        _create_tree(tmp_path)
        result = _get_folder_description({"folder_path": str(tmp_path), "max_depth": 1}, {})
        assert "a.py" in result
        assert "b.py" in result
        assert "c.py" not in result
        assert "d.py" not in result

    def test_explicit_depth_4_shows_all(self, tmp_path):
        _create_tree(tmp_path)
        result = _get_folder_description({"folder_path": str(tmp_path), "max_depth": 4}, {})
        assert "a.py" in result
        assert "b.py" in result
        assert "c.py" in result
        assert "d.py" in result

    def test_truncation_message_when_files_excluded(self, tmp_path):
        _create_tree(tmp_path)
        result = _get_folder_description({"folder_path": str(tmp_path), "max_depth": 1}, {})
        # Should indicate that files were excluded
        assert "not shown" in result.lower() or "excluded" in result.lower() or "deeper" in result.lower()
