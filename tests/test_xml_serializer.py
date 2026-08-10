# [desc] Tests for XML serialization and round-trip parsing of tool calls and results. [/desc]
"""Tests for xml_tool_protocol.serializer — produces XML text for tool calls and results."""
from __future__ import annotations

import pytest


def _serialize_call(tc):
    from xml_tool_protocol import serialize_tool_call
    return serialize_tool_call(tc)


def _serialize_result(tool_call_id, content):
    from xml_tool_protocol import serialize_tool_result
    return serialize_tool_result(tool_call_id, content)


def _parse(xml):
    from xml_tool_protocol import XmlToolStreamParser
    p = XmlToolStreamParser()
    _, completed = p.feed(xml)
    return completed


def test_serialize_simple_call():
    xml = _serialize_call({"id": "r1", "name": "Read", "input": {"file_path": "a.py"}})
    assert '<tool_use' in xml
    assert 'name="Read"' in xml
    assert 'id="r1"' in xml
    assert '<param name="file_path">a.py</param>' in xml
    assert xml.rstrip().endswith("</tool_use>")


def test_serialize_call_no_params():
    xml = _serialize_call({"id": "l1", "name": "ListAgentTasks", "input": {}})
    assert 'name="ListAgentTasks"' in xml
    assert 'id="l1"' in xml
    assert "<param" not in xml


def test_serialize_value_with_angle_bracket_uses_cdata():
    code = "if a < b: print('<html>')"
    xml = _serialize_call({"id": "w1", "name": "Write", "input": {"content": code}})
    assert "<![CDATA[" in xml
    assert "]]>" in xml
    assert code in xml


def test_serialize_value_with_ampersand_uses_cdata():
    payload = "a && b"
    xml = _serialize_call({"id": "b1", "name": "Bash", "input": {"command": payload}})
    assert "<![CDATA[" in xml
    assert payload in xml


def test_serialize_value_containing_cdata_terminator_escapes():
    payload = "abc ]]> def"
    xml = _serialize_call({"id": "w1", "name": "Write", "input": {"content": payload}})
    assert "]]]]><![CDATA[>" in xml
    assert payload not in xml or xml.count("]]>") > 1


def test_serialize_plain_ascii_no_cdata():
    xml = _serialize_call({"id": "r1", "name": "Read", "input": {"file_path": "foo.py"}})
    assert "<![CDATA[" not in xml


def test_serialize_integer_value():
    xml = _serialize_call({"id": "r1", "name": "Read", "input": {"offset": 100, "limit": 50}})
    assert "100" in xml
    assert "50" in xml


def test_serialize_boolean_value():
    xml = _serialize_call({"id": "g1", "name": "Grep", "input": {"pattern": "foo", "-i": True}})
    assert "true" in xml.lower() or "True" in xml


def test_serialize_list_value():
    xml = _serialize_call({"id": "t1", "name": "TaskCreate", "input": {"tags": ["a", "b", "c"]}})
    assert "a" in xml and "b" in xml and "c" in xml


def test_roundtrip_read():
    tc = {"id": "r1", "name": "Read", "input": {"file_path": "src/main.py"}}
    parsed = _parse(_serialize_call(tc))
    assert len(parsed) == 1
    assert parsed[0] == tc


def test_roundtrip_write_with_python_code():
    code = """import json

def fetch(url: str) -> dict:
    if url < "":
        raise ValueError("bad url & stuff")
    return {"ok": True}
"""
    tc = {"id": "w1", "name": "Write", "input": {"file_path": "a.py", "content": code}}
    parsed = _parse(_serialize_call(tc))
    assert len(parsed) == 1
    assert parsed[0]["input"]["content"] == code
    assert parsed[0]["input"]["file_path"] == "a.py"
    assert parsed[0]["name"] == "Write"
    assert parsed[0]["id"] == "w1"


def test_roundtrip_grep_with_regex():
    tc = {
        "id": "g1",
        "name": "Grep",
        "input": {"pattern": r"log\.(Error|Fatal)\s+<.*>", "glob": "*.go"},
    }
    parsed = _parse(_serialize_call(tc))
    assert parsed[0]["input"]["pattern"] == r"log\.(Error|Fatal)\s+<.*>"
    assert parsed[0]["input"]["glob"] == "*.go"


def test_roundtrip_bash_with_shell_quotes():
    tc = {
        "id": "b1",
        "name": "Bash",
        "input": {"command": "grep -E '^a&b<c' file.txt | head -5"},
    }
    parsed = _parse(_serialize_call(tc))
    assert parsed[0]["input"]["command"] == "grep -E '^a&b<c' file.txt | head -5"


def test_roundtrip_value_with_cdata_terminator():
    tc = {
        "id": "w1",
        "name": "Write",
        "input": {"content": "abc ]]> middle ]]> end"},
    }
    parsed = _parse(_serialize_call(tc))
    assert parsed[0]["input"]["content"] == "abc ]]> middle ]]> end"


def test_roundtrip_multiple_calls():
    calls = [
        {"id": "r1", "name": "Read", "input": {"file_path": "a.py"}},
        {"id": "r2", "name": "Read", "input": {"file_path": "b.py"}},
        {"id": "b1", "name": "Bash", "input": {"command": "ls"}},
    ]
    xml = "\n".join(_serialize_call(tc) for tc in calls)
    parsed = _parse(xml)
    assert parsed == calls


def test_serialize_result_simple():
    xml = _serialize_result("r1", "file contents here")
    assert '<tool_result' in xml
    assert 'id="r1"' in xml
    assert "file contents here" in xml
    assert xml.rstrip().endswith("</tool_result>")


def test_serialize_result_with_special_chars_uses_cdata():
    content = "<error> a & b ]]> after"
    xml = _serialize_result("r1", content)
    assert "<![CDATA[" in xml
    assert "]]]]><![CDATA[>" in xml


def test_attribute_escaping_in_name():
    """Ensure a tool name with a quote gets escaped or rejected cleanly."""
    tc = {"id": "r1", "name": 'Read"evil', "input": {}}
    xml = _serialize_call(tc)
    assert 'name="Read"evil"' not in xml
