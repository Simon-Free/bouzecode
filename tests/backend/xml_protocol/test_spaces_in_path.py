# [desc] Tests that file paths containing spaces are handled correctly by XML parser and file ops layers. [/desc]
"""Tests that paths with spaces are handled correctly through all layers."""
import os
import pytest
from bouzecode.backend.xml_tool_protocol.parser import _scan_params, _unwrap_cdata, XmlToolStreamParser
from bouzecode.backend.tools.ops.file_ops import _write, _read, _edit


def _split(items):
    """Adapt feed()'s interleaved list to (visible_text, completed_tools)."""
    return (
        "".join(i for i in items if isinstance(i, str)),
        [i for i in items if isinstance(i, dict)],
    )


# ── XML parser layer ──────────────────────────────────────────────────────────

class TestXmlParserSpaces:
    """Verify the XML parser preserves spaces in param values."""

    def test_plain_value_with_spaces(self):
        body = '<param name="file_path">C:\\Users\\my folder\\file.py</param>'
        params = _scan_params(body)
        assert params["file_path"] == "C:\\Users\\my folder\\file.py"

    def test_cdata_value_with_spaces(self):
        body = '<param name="file_path"><![CDATA[C:\\Users\\my folder\\file.py]]></param>'
        params = _scan_params(body)
        assert params["file_path"] == "C:\\Users\\my folder\\file.py"

    def test_multiple_spaces_in_path(self):
        body = '<param name="file_path">C:\\a b c\\d e f\\g h.txt</param>'
        params = _scan_params(body)
        assert params["file_path"] == "C:\\a b c\\d e f\\g h.txt"

    def test_content_param_with_spaces_in_path(self):
        body = (
            '<param name="file_path">C:\\folder with spaces\\test.py</param>'
            '<param name="content"><![CDATA[print("hello")]]></param>'
        )
        params = _scan_params(body)
        assert params["file_path"] == "C:\\folder with spaces\\test.py"
        assert params["content"] == 'print("hello")'

    def test_stream_parser_preserves_spaces(self):
        parser = XmlToolStreamParser()
        xml = (
            '<tool_use name="Write" id="w1">'
            '<param name="file_path">C:\\my dir\\sub dir\\file.py</param>'
            '<param name="content"><![CDATA[x = 1]]></param>'
            '</tool_use>'
        )
        _, calls = _split(parser.feed(xml))
        calls += parser.finalize()
        assert len(calls) == 1
        assert calls[0]["input"]["file_path"] == "C:\\my dir\\sub dir\\file.py"
        assert calls[0]["input"]["content"] == "x = 1"

    def test_stream_parser_chunked_spaces(self):
        """Feed the XML in small chunks to ensure streaming doesn't break spaces."""
        parser = XmlToolStreamParser()
        xml = (
            '<tool_use name="Read" id="r1">'
            '<param name="file_path">C:\\path with spaces\\deep folder\\f.py</param>'
            '</tool_use>'
        )
        calls_all = []
        for ch in [xml[i:i+7] for i in range(0, len(xml), 7)]:
            _, calls = _split(parser.feed(ch))
            calls_all.extend(calls)
        calls_all.extend(parser.finalize())
        assert len(calls_all) == 1
        assert calls_all[0]["input"]["file_path"] == "C:\\path with spaces\\deep folder\\f.py"


# ── File ops layer ────────────────────────────────────────────────────────────

class TestFileOpsSpaces:
    """Verify _write, _read, _edit work with spaces in paths."""

    def test_write_and_read_with_spaces(self, tmp_path):
        dir_with_spaces = tmp_path / "my folder" / "sub dir"
        file_path = str(dir_with_spaces / "test file.py")
        result = _write(file_path, "hello = 1\n")
        assert "Created" in result or "Error" not in result
        assert os.path.exists(file_path)
        content = _read(file_path)
        assert "hello = 1" in content

    def test_write_deep_nested_spaces(self, tmp_path):
        deep = tmp_path / "a b" / "c d" / "e f"
        fp = str(deep / "g h.txt")
        result = _write(fp, "deep content\n")
        assert "Created" in result
        assert os.path.exists(fp)

    def test_edit_with_spaces(self, tmp_path):
        fp = str(tmp_path / "folder with spaces" / "edit me.py")
        _write(fp, "old_value = 1\n")
        result = _edit(fp, "old_value = 1", "new_value = 2")
        assert "Changes applied" in result
        content = _read(fp)
        assert "new_value = 2" in content
        assert "old_value" not in content

    def test_read_nonexistent_spaces(self, tmp_path):
        fp = str(tmp_path / "does not exist" / "file.py")
        result = _read(fp)
        assert "Error" in result

    def test_write_overwrite_with_spaces(self, tmp_path):
        fp = str(tmp_path / "my dir" / "file.py")
        _write(fp, "version = 1\n")
        result = _write(fp, "version = 2\n")
        assert "updated" in result.lower() or "Changes" in result or "File updated" in result
        content = _read(fp)
        assert "version = 2" in content


# ── unwrap_cdata edge cases ───────────────────────────────────────────────────

class TestUnwrapCdataSpaces:

    def test_path_no_cdata(self):
        assert _unwrap_cdata("C:\\Users\\my folder\\file.py") == "C:\\Users\\my folder\\file.py"

    def test_path_in_cdata(self):
        val = "<![CDATA[C:\\Users\\my folder\\file.py]]>"
        assert _unwrap_cdata(val) == "C:\\Users\\my folder\\file.py"

    def test_path_with_whitespace_around_cdata(self):
        val = "  <![CDATA[C:\\a b\\c.py]]>  "
        assert _unwrap_cdata(val) == "C:\\a b\\c.py"

    def test_plain_spaces_preserved(self):
        assert _unwrap_cdata("  hello world  ") == "  hello world  "
