# [desc] Unit tests for tool registry registration, retrieval, execution, and output truncation. [/desc]
from __future__ import annotations

import re

import pytest

from bouzecode.backend.core.tool_registry import (
    ToolDef,
    clear_registry,
    execute_tool,
    get_all_tools,
    get_tool,
    get_tool_schemas,
    register_tool,
)


@pytest.fixture(autouse=True)
def _clean_registry():
    """Reset registry before each test."""
    clear_registry()
    yield
    clear_registry()


def _make_echo_tool(name: str = "echo", read_only: bool = False) -> ToolDef:
    """Helper to build a simple echo tool."""
    schema = {
        "name": name,
        "description": f"Echo tool ({name})",
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "text to echo"},
            },
            "required": ["text"],
        },
    }

    def func(params: dict, config: dict) -> str:
        return params["text"]

    return ToolDef(
        name=name,
        schema=schema,
        func=func,
        read_only=read_only,
        concurrent_safe=True,
    )


# ------------------------------------------------------------------
# register and get
# ------------------------------------------------------------------

def test_register_and_get():
    tool = _make_echo_tool()
    register_tool(tool)
    result = get_tool("echo")
    assert result is not None
    assert result.name == "echo"


def test_get_unknown_returns_none():
    assert get_tool("no_such_tool") is None


# ------------------------------------------------------------------
# get_all_tools
# ------------------------------------------------------------------

def test_get_all_tools_empty():
    assert get_all_tools() == []


def test_get_all_tools():
    register_tool(_make_echo_tool("a"))
    register_tool(_make_echo_tool("b"))
    names = [t.name for t in get_all_tools()]
    assert sorted(names) == ["a", "b"]


# ------------------------------------------------------------------
# get_tool_schemas
# ------------------------------------------------------------------

def test_get_tool_schemas():
    register_tool(_make_echo_tool("echo"))
    schemas = get_tool_schemas()
    assert len(schemas) == 1
    assert schemas[0]["name"] == "echo"


# ------------------------------------------------------------------
# execute_tool
# ------------------------------------------------------------------

def test_execute_tool():
    register_tool(_make_echo_tool())
    result = execute_tool("echo", {"text": "hello"}, config={})
    assert result == "hello"


def test_execute_unknown_tool():
    result = execute_tool("missing", {}, config={})
    assert "n'existe pas dans ce harnais" in result
    assert "Tous les outils dont tu disposes" in result   # refus actionnable, pas juste "not found"


# ------------------------------------------------------------------
# output truncation
# ------------------------------------------------------------------

def test_output_truncation():
    def big_func(params: dict, config: dict) -> str:
        return "x" * 100

    tool = ToolDef(
        name="big",
        schema={"name": "big", "description": "big", "input_schema": {"type": "object", "properties": {}}},
        func=big_func,
        read_only=True,
        concurrent_safe=True,
    )
    register_tool(tool)

    result = execute_tool("big", {}, config={}, max_output=40)
    # Head (1/3) + tail kept around a marker that points to the FULL output on disk;
    # the kept text never exceeds max_output.
    head, _, rest = result.partition("\n\n[...output truncated")
    tail = rest.rsplit("\n\n", 1)[-1]
    assert head == "x" * 13 and tail == "x" * 27
    saved = re.search(r'Read\(file_path="([^"]+)"\)', result).group(1)
    assert open(saved, encoding="utf-8").read() == "x" * 100


def test_max_tool_output_from_config_caps_the_result():
    """`max_tool_output` (config) was defined but read nowhere: now it is the cap."""
    register_tool(ToolDef(
        name="big2",
        schema={"name": "big2", "description": "big", "input_schema": {"type": "object", "properties": {}}},
        func=lambda p, c: "y" * 5000, read_only=True, concurrent_safe=True,
    ))
    result = execute_tool("big2", {}, config={"max_tool_output": 1000})
    head, _, rest = result.partition("\n\n[...output truncated")
    assert len(head) + len(rest.rsplit("\n\n", 1)[-1]) == 1000 and rest


def test_no_truncation_when_within_limit():
    register_tool(_make_echo_tool())
    result = execute_tool("echo", {"text": "short"}, config={})
    assert result == "short"


def test_snippetable_tool_is_never_truncated():
    """Snippetable results are owned by the snippet wire — execute_tool must let
    the full content through, even past max_output, so the model can snippet the
    middle (regression: get_br_content lost the middle of large BRs)."""
    big = "y" * 1000

    def big_func(params: dict, config: dict) -> str:
        return big

    tool = ToolDef(
        name="big_snip",
        schema={"name": "big_snip", "description": "big", "input_schema": {"type": "object", "properties": {}}},
        func=big_func,
        read_only=True,
        concurrent_safe=True,
        snippetable=True,
    )
    register_tool(tool)

    result = execute_tool("big_snip", {}, config={}, max_output=40)
    assert result == big
    assert "truncated" not in result


# ------------------------------------------------------------------
# duplicate register overwrites
# ------------------------------------------------------------------

def test_duplicate_register_overwrites():
    register_tool(_make_echo_tool("dup"))

    def new_func(params: dict, config: dict) -> str:
        return "new"

    replacement = ToolDef(
        name="dup",
        schema={"name": "dup", "description": "new", "input_schema": {"type": "object", "properties": {}}},
        func=new_func,
        read_only=False,
        concurrent_safe=False,
    )
    register_tool(replacement)

    assert len(get_all_tools()) == 1
    result = execute_tool("dup", {}, config={})
    assert result == "new"


# ------------------------------------------------------------------
# required param empty/blank/missing -> explicit refusal (no execution)
# ------------------------------------------------------------------

def test_execute_tool_missing_required_param_blocks():
    """An empty-string required param is a serialization mishap: refuse to run
    and return an explicit message instead of executing a no-op (regression:
    Bash command="" listed the cwd and trapped the model in a retry loop)."""
    register_tool(_make_echo_tool())
    result = execute_tool("echo", {"text": ""}, config={})
    assert "required" in result.lower()
    assert "empty" in result.lower()
    assert "text" in result
    # func was NOT called: it would have returned "" (the echoed text)
    assert result != ""


def test_execute_tool_whitespace_required_param_blocks():
    register_tool(_make_echo_tool())
    result = execute_tool("echo", {"text": "   "}, config={})
    assert "required" in result.lower()
    assert "text" in result


def test_execute_tool_absent_required_param_blocks():
    register_tool(_make_echo_tool())
    result = execute_tool("echo", {}, config={})
    assert "required" in result.lower()
    assert "text" in result


def test_blank_required_message_names_the_cdata_wrapper():
    """The refusal must SAY what to wrap the value in. The literal '<![CDATA[' was
    once eaten by an edit pass, leaving 'was not wrapped in ....' — an instruction
    nothing can act on. Observed in prod: 66 tool calls over 4 minutes guessing at
    [], JSON lists and random CDATA before giving up. Invisible on re-read, so a
    test must scream about it."""
    register_tool(_make_echo_tool())
    result = execute_tool("echo", {"text": ""}, config={})
    assert "<![CDATA[" in result, f"guard message lost its CDATA literal: {result!r}"


def test_execute_tool_valid_required_passes():
    """Non-regression: a filled required param still executes normally."""
    register_tool(_make_echo_tool())
    result = execute_tool("echo", {"text": "hi"}, config={})
    assert result == "hi"
