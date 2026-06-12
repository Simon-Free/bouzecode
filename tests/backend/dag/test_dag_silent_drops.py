# [desc] Tests DAG silent-drop paths for depends_on/tool_call_alias as XML attrs, comma strings, and unresolved refs. [/desc]
from __future__ import annotations

import io
import contextlib

from bouzecode.backend.agent.dag import _build_dag_levels, _coerce_list
from bouzecode.backend.agent.id_uniquify import uniquify_tool_call_ids
from bouzecode.backend.xml_tool_protocol.parser import XmlToolStreamParser


class _FakeState:
    def __init__(self, prior_ids, turn_count):
        self.messages = [
            {"role": "assistant",
             "tool_calls": [{"id": tid, "name": "Dummy", "input": {}} for tid in prior_ids]}
        ]
        self.turn_count = turn_count
        self.context_state = None


def _build_and_capture(tcs):
    stderr_buf = io.StringIO()
    with contextlib.redirect_stderr(stderr_buf):
        levels, deps = _build_dag_levels(tcs)
    return levels, deps, stderr_buf.getvalue()


class TestXmlParserAbsorbsSchedulingAttributes:
    """Root cause: the XML parser was ignoring all attributes except name/id.
    The model sometimes emits depends_on / tool_call_alias as attributes — those
    must be routed into input so the DAG can see them."""

    def test_depends_on_as_single_attribute(self):
        xml = (
            '<tool_use name="Write" id="w1"><param name="file_path">/tmp/a.py</param>'
            '<param name="content">hi</param></tool_use>'
            '<tool_use name="Bash" id="b1" depends_on="w1">'
            '<param name="command">echo hi</param></tool_use>'
        )
        tcs = [item for item in XmlToolStreamParser().feed(xml) if isinstance(item, dict)]
        bash = next(tc for tc in tcs if tc["id"] == "b1")
        assert "depends_on" in bash["input"]
        # End-to-end: DAG resolves the dep
        _, deps = _build_dag_levels(tcs)
        assert deps["b1"] == {"w1"}

    def test_depends_on_as_comma_attribute_splits(self):
        xml = (
            '<tool_use name="Bash" id="push1"><param name="command">git push</param></tool_use>'
            '<tool_use name="Write" id="w1"><param name="file_path">/tmp/a.py</param>'
            '<param name="content">hi</param></tool_use>'
            '<tool_use name="Bash" id="run1" depends_on="push1,w1">'
            '<param name="command">echo done</param></tool_use>'
        )
        tcs = [item for item in XmlToolStreamParser().feed(xml) if isinstance(item, dict)]
        run1 = next(tc for tc in tcs if tc["id"] == "run1")
        assert "depends_on" in run1["input"]
        # End-to-end: both deps resolve after comma split in _coerce_list
        levels, deps = _build_dag_levels(tcs)
        assert deps["run1"] == {"push1", "w1"}
        assert len(levels) >= 2  # push1,w1 first level ; run1 after

    def test_tool_call_alias_as_attribute(self):
        xml = (
            '<tool_use name="Write" id="abc" tool_call_alias="w1">'
            '<param name="file_path">/tmp/a.py</param>'
            '<param name="content">hi</param></tool_use>'
            '<tool_use name="Bash" id="b1">'
            '<param name="command">echo hi</param>'
            '<param name="depends_on">["w1"]</param></tool_use>'
        )
        tcs = [item for item in XmlToolStreamParser().feed(xml) if isinstance(item, dict)]
        levels, deps = _build_dag_levels(tcs)
        assert deps["b1"] == {"abc"}

    def test_body_param_wins_over_attribute(self):
        """If both the attribute and a <param> version are present, <param> takes precedence."""
        xml = (
            '<tool_use name="Bash" id="b1" depends_on="attr_val">'
            '<param name="command">hi</param>'
            '<param name="depends_on">["param_val"]</param></tool_use>'
        )
        tcs = [item for item in XmlToolStreamParser().feed(xml) if isinstance(item, dict)]
        # param form wins — still the raw JSON string, DAG will coerce it later
        assert tcs[0]["input"]["depends_on"] == '["param_val"]'


class TestUniquifyPreservesJsonStringDepends:
    """Reproduces a live stderr bug: when IDs collide and depends_on is a JSON
    string like '["w1"]', uniquify was wrapping it to ['["w1"]'] without
    parsing — _coerce_list then returned the list as-is and the DAG dropped
    the reference as unresolvable."""

    def test_json_string_depends_on_resolves_after_uniquify(self):
        state = _FakeState(prior_ids=["w1", "b1"], turn_count=16)
        tool_calls = [
            {"id": "w1", "name": "Write",
             "input": {"file_path": "/tmp/script.py", "content": "x"}},
            {"id": "b1", "name": "Bash",
             "input": {"command": "python /tmp/script.py",
                       "depends_on": '["w1"]'}},
        ]
        remap = uniquify_tool_call_ids(tool_calls, state)
        assert remap == {"w1": "t16_w1", "b1": "t16_b1"}
        bash = next(tc for tc in tool_calls if tc["name"] == "Bash")
        # The JSON string was parsed, then the element remapped to the fresh id
        assert bash["input"]["depends_on"] == ["t16_w1"]

        # End-to-end: DAG correctly resolves the dep
        levels, deps = _build_dag_levels(tool_calls)
        assert deps["t16_b1"] == {"t16_w1"}
        assert len(levels) == 2

    def test_comma_string_depends_on_resolves_after_uniquify(self):
        state = _FakeState(prior_ids=["w1", "b1", "push1"], turn_count=16)
        tool_calls = [
            {"id": "push1", "name": "Bash", "input": {"command": "git push"}},
            {"id": "w1", "name": "Write",
             "input": {"file_path": "/tmp/a.py", "content": "x"}},
            {"id": "b1", "name": "Bash",
             "input": {"command": "echo done", "depends_on": "push1,w1"}},
        ]
        uniquify_tool_call_ids(tool_calls, state)
        bash = next(tc for tc in tool_calls if tc["id"] == "t16_b1")
        assert bash["input"]["depends_on"] == ["t16_push1", "t16_w1"]


class TestCoerceListSplitsCommaString:
    def test_plain_comma_split(self):
        assert _coerce_list("w1,b1") == ["w1", "b1"]

    def test_comma_with_spaces(self):
        assert _coerce_list("w1, b1 , c1") == ["w1", "b1", "c1"]

    def test_json_still_wins(self):
        assert _coerce_list('["w1", "b1"]') == ["w1", "b1"]

    def test_single_token_unchanged(self):
        assert _coerce_list("w1") == ["w1"]

    def test_list_unchanged(self):
        assert _coerce_list(["w1", "b1"]) == ["w1", "b1"]

    def test_empty_cases(self):
        assert _coerce_list("") == []


class TestCoerceListSingleQuotes:
    """Handle Python repr with single quotes — the LLM sometimes emits these."""

    def test_single_element_single_quotes(self):
        assert _coerce_list("['t1']") == ["t1"]

    def test_multiple_elements_single_quotes(self):
        assert _coerce_list("['m1', 'm2', 'm3']") == ["m1", "m2", "m3"]

    def test_mixed_quotes_still_works(self):
        # JSON double quotes should still be preferred
        assert _coerce_list('["w1", "b1"]') == ["w1", "b1"]

    def test_single_element_no_brackets(self):
        # Plain string without brackets should still work
        assert _coerce_list("t1") == ["t1"]
        assert _coerce_list(None) == []
        assert _coerce_list(",,") == []


class TestDagLogsUnresolvedReferences:
    """When depends_on references an alias/ID not present in this turn,
    the DAG now emits a stderr warning (instead of silently dropping)."""

    def test_typo_alias_is_logged(self):
        tcs = [
            {"id": "tc_A", "name": "Write",
             "input": {"file_path": "/tmp/a.py", "tool_call_alias": "writefile"}},
            {"id": "tc_B", "name": "Bash",
             "input": {"command": "echo hi", "depends_on": ["writeFile"]}},
        ]
        _, _, stderr = _build_and_capture(tcs)
        assert "[dag]" in stderr
        assert "writeFile" in stderr
        assert "tc_B" in stderr

    def test_id_from_prior_turn_is_logged(self):
        tcs = [
            {"id": "new_A", "name": "Write",
             "input": {"file_path": "/tmp/a.py", "tool_call_alias": "a1"}},
            {"id": "new_B", "name": "Bash",
             "input": {"command": "echo hi", "depends_on": ["tc_from_last_turn"]}},
        ]
        _, _, stderr = _build_and_capture(tcs)
        assert "tc_from_last_turn" in stderr
        assert "new_B" in stderr

    def test_resolved_refs_no_warning(self):
        tcs = [
            {"id": "a", "name": "Write",
             "input": {"file_path": "/tmp/a.py", "tool_call_alias": "w1"}},
            {"id": "b", "name": "Bash",
             "input": {"command": "echo hi", "depends_on": ["w1"]}},
        ]
        _, _, stderr = _build_and_capture(tcs)
        # Only successful resolution, no [dag] dropped message
        assert "dropped" not in stderr.lower()

    def test_mixed_good_and_bad_logs_only_bad(self):
        tcs = [
            {"id": "a", "name": "Write",
             "input": {"file_path": "/tmp/a.py", "tool_call_alias": "w1"}},
            {"id": "b", "name": "Write",
             "input": {"file_path": "/tmp/b.py", "tool_call_alias": "w2"}},
            {"id": "c", "name": "Bash",
             "input": {"command": "echo hi", "depends_on": ["w1", "bogus"]}},
        ]
        _, deps, stderr = _build_and_capture(tcs)
        assert deps["c"] == {"a"}
        # Dropped list before the "—" separator should contain only the bad ref
        dropped_section = stderr.split("—")[0]
        assert "bogus" in dropped_section
        assert "w1" not in dropped_section
