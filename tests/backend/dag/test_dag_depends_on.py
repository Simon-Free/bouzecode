# [desc] Tests DAG dependency resolution: depends_on string coercion and auto-injection of Write→Bash deps
# <tool_use name="FinalAnswer" id="r1"><param name="answer">Tests DAG dependency resolution: depends_on string coercion and auto-injection of Write→Bash deps</param></tool_use> [/desc]
"""Tests for depends_on parsing (string coercion) and auto-injection of Write->Bash deps."""
from __future__ import annotations

from bouzecode.backend.agent.dag import _build_dag_levels, _coerce_list


class TestCoerceList:
    def test_already_list(self):
        assert _coerce_list(["w1", "w2"]) == ["w1", "w2"]

    def test_json_string_array(self):
        assert _coerce_list('["w1"]') == ["w1"]

    def test_json_string_multi(self):
        assert _coerce_list('["w1", "e2"]') == ["w1", "e2"]

    def test_plain_string(self):
        assert _coerce_list("w1") == ["w1"]

    def test_none(self):
        assert _coerce_list(None) == []

    def test_empty_string(self):
        assert _coerce_list("") == []

    def test_empty_list(self):
        assert _coerce_list([]) == []

    def test_json_string_with_spaces(self):
        assert _coerce_list('  ["w1"]  ') == ["w1"]


class TestDependsOnStringParsing:
    def test_depends_on_as_json_string_creates_dependency(self):
        """The XML parser returns depends_on as '["w1"]' string — DAG must parse it."""
        tcs = [
            {"id": "t1", "name": "Write", "input": {"file_path": "test.py", "tool_call_alias": "w1"}},
            {"id": "t2", "name": "Bash", "input": {"command": "python test.py", "depends_on": '["w1"]'}},
        ]
        levels, deps = _build_dag_levels(tcs)
        assert len(levels) == 2
        assert levels[0][0]["id"] == "t1"
        assert levels[1][0]["id"] == "t2"
        assert "t1" in deps["t2"]

    def test_depends_on_as_list_still_works(self):
        tcs = [
            {"id": "t1", "name": "Write", "input": {"file_path": "test.py", "tool_call_alias": "w1"}},
            {"id": "t2", "name": "Bash", "input": {"command": "python test.py", "depends_on": ["w1"]}},
        ]
        levels, deps = _build_dag_levels(tcs)
        assert len(levels) == 2
        assert "t1" in deps["t2"]

    def test_depends_on_as_plain_string_alias(self):
        tcs = [
            {"id": "t1", "name": "Write", "input": {"file_path": "test.py", "tool_call_alias": "w1"}},
            {"id": "t2", "name": "Bash", "input": {"command": "python test.py", "depends_on": "w1"}},
        ]
        levels, deps = _build_dag_levels(tcs)
        assert len(levels) == 2
        assert "t1" in deps["t2"]


class TestAutoInjectWriteBashDeps:
    def test_auto_inject_when_bash_references_written_file(self):
        tcs = [
            {"id": "w1", "name": "Write", "input": {"file_path": "/tmp/script.py"}},
            {"id": "b1", "name": "Bash", "input": {"command": "python /tmp/script.py"}},
        ]
        levels, deps = _build_dag_levels(tcs)
        assert len(levels) == 2
        assert levels[0][0]["id"] == "w1"
        assert levels[1][0]["id"] == "b1"
        assert "w1" in deps["b1"]

    def test_no_false_positive_different_file(self):
        tcs = [
            {"id": "w1", "name": "Write", "input": {"file_path": "/tmp/script.py"}},
            {"id": "b1", "name": "Bash", "input": {"command": "python /tmp/other.py"}},
        ]
        levels, deps = _build_dag_levels(tcs)
        assert len(levels) == 1
        assert "w1" not in deps.get("b1", set())

    def test_explicit_dep_not_duplicated(self):
        tcs = [
            {"id": "t1", "name": "Write", "input": {"file_path": "/tmp/script.py", "tool_call_alias": "w1"}},
            {"id": "t2", "name": "Bash", "input": {"command": "python /tmp/script.py", "depends_on": ["w1"]}},
        ]
        levels, deps = _build_dag_levels(tcs)
        assert len(levels) == 2
        assert deps["t2"] == {"t1"}

    def test_auto_inject_with_windows_path(self):
        tcs = [
            {"id": "w1", "name": "Write", "input": {"file_path": "C:\\Users\\test\\script.py"}},
            {"id": "b1", "name": "Bash", "input": {"command": "python C:\\Users\\test\\script.py"}},
        ]
        levels, deps = _build_dag_levels(tcs)
        assert len(levels) == 2
        assert "w1" in deps["b1"]

    def test_auto_inject_edit_tool(self):
        tcs = [
            {"id": "e1", "name": "Edit", "input": {"file_path": "/tmp/config.py"}},
            {"id": "b1", "name": "Bash", "input": {"command": "python /tmp/config.py"}},
        ]
        levels, deps = _build_dag_levels(tcs)
        assert len(levels) == 2
        assert "e1" in deps["b1"]

    def test_delete_depends_on_bash(self):
        """Write -> Run -> Delete chain: delete should not auto-inject dep on Write."""
        tcs = [
            {"id": "w1", "name": "Write", "input": {"file_path": "/tmp/script.py", "tool_call_alias": "w1"}},
            {"id": "b1", "name": "Bash", "input": {"command": "python /tmp/script.py", "depends_on": ["w1"], "tool_call_alias": "b1"}},
            {"id": "d1", "name": "Bash", "input": {"command": "del /tmp/script.py", "depends_on": ["b1"]}},
        ]
        levels, deps = _build_dag_levels(tcs)
        assert len(levels) == 3
