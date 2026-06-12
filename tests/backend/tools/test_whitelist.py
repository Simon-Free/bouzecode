# [desc] Tests that only whitelisted tools appear in schemas and disabled tools return error messages. [/desc]
"""Only the _DEFAULT_ENABLED whitelist is sent to the model; every other
registered tool is disabled at import time (token-budget choice) and answers
with a 'currently disabled' error if invoked anyway."""
import bouzecode.backend.tools  # noqa: F401 — triggers builtin registration + whitelist


def _schema_names():
    from bouzecode.backend.core.tool_registry import get_tool_schemas
    return {s["name"] for s in get_tool_schemas()}


def test_whitelisted_tools_exactly_match_schemas():
    from bouzecode.backend.tools.registration import _DEFAULT_ENABLED

    names = _schema_names()
    assert names == set(_DEFAULT_ENABLED), (
        f"schemas/whitelist drift: extra={names - set(_DEFAULT_ENABLED)}, "
        f"missing={set(_DEFAULT_ENABLED) - names}"
    )


def test_non_whitelisted_tool_absent_and_errors_when_called():
    from bouzecode.backend.core.tool_registry import execute_tool

    assert "EnterPlanMode" not in _schema_names()
    result = execute_tool("EnterPlanMode", {}, {})
    assert "currently disabled" in result
