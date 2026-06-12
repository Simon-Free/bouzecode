# [desc] Tests that invalid tool parameters produce error messages listing valid parameter names. [/desc]
"""When a tool call has an unknown param name or a wrong-typed value, the error
must list the valid parameters (so the model can self-correct in one shot).
Covers both the XML and native-JSON paths since both go through execute_tool.
"""
from bouzecode.backend.core.tool_registry import (
    ToolDef, register_tool, push_local_overlay, pop_local_overlay, execute_tool,
)


def _dummy() -> ToolDef:
    return ToolDef(name="DummyTool", schema={
        "name": "DummyTool", "description": "x",
        "input_schema": {"type": "object", "properties": {
            "file_path": {"type": "string"}, "count": {"type": "integer"}},
            "required": ["file_path"]},
    }, func=lambda params, config: f"ok:{sorted(params)}")


class TestInvalidParamListing:
    def setup_method(self):
        push_local_overlay()
        register_tool(_dummy())

    def teardown_method(self):
        pop_local_overlay()

    def test_unknown_param_name_lists_valid(self):
        out = execute_tool("DummyTool", {"file_path": "a", "flie_path": "b"}, {})
        assert "unknown parameter" in out.lower()
        assert "flie_path" in out                 # the offending name
        assert "file_path" in out and "count" in out  # the valid set

    def test_wrong_type_lists_valid(self):
        out = execute_tool("DummyTool", {"file_path": "a", "count": "notanint"}, {})
        assert "invalid parameter format" in out.lower()
        assert "Valid parameters:" in out
        assert "file_path" in out and "count" in out

    def test_scheduling_params_are_accepted(self):
        out = execute_tool("DummyTool", {"file_path": "a", "depends_on": ["w1"],
                                         "tool_call_alias": "x"}, {})
        assert out.startswith("ok:")

    def test_valid_call_passes_through(self):
        out = execute_tool("DummyTool", {"file_path": "a", "count": 3}, {})
        assert out.startswith("ok:")
