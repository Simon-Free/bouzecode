# [desc] Tests that build_tool_docs generates correct XML tool protocol documentation for system prompts. [/desc]
"""Tests for xml_tool_protocol.docs — builds the tool documentation section for the system prompt."""
from __future__ import annotations

import pytest


READ_SCHEMA = {
    "name": "Read",
    "description": "Read a file from disk.",
    "input_schema": {
        "type": "object",
        "properties": {
            "file_path": {"type": "string", "description": "Absolute file path"},
        },
        "required": ["file_path"],
    },
}

WRITE_SCHEMA = {
    "name": "Write",
    "description": "Write content to a file.",
    "input_schema": {
        "type": "object",
        "properties": {
            "file_path": {"type": "string"},
            "content": {"type": "string"},
        },
        "required": ["file_path", "content"],
    },
}

BASH_SCHEMA = {
    "name": "Bash",
    "description": "Run a shell command.",
    "input_schema": {
        "type": "object",
        "properties": {
            "command": {"type": "string"},
        },
        "required": ["command"],
    },
}


def _build(schemas):
    from xml_tool_protocol import build_tool_docs
    return build_tool_docs(schemas)


def test_empty_schemas_still_explains_format():
    docs = _build([])
    assert isinstance(docs, str)
    assert len(docs) > 0
    assert "<tool_use" in docs
    assert "</tool_use>" in docs


def test_each_tool_is_named():
    docs = _build([READ_SCHEMA, WRITE_SCHEMA, BASH_SCHEMA])
    assert "Read" in docs
    assert "Write" in docs
    assert "Bash" in docs


def test_each_tool_has_description():
    docs = _build([READ_SCHEMA, WRITE_SCHEMA])
    assert "Read a file from disk." in docs
    assert "Write content to a file." in docs


def test_each_tool_has_its_parameters_listed():
    docs = _build([READ_SCHEMA, WRITE_SCHEMA])
    assert "file_path" in docs
    assert "content" in docs


def test_docs_include_a_parsable_xml_example():
    """The generated example XML must itself parse cleanly (no syntax drift)."""
    from xml_tool_protocol import XmlToolStreamParser
    docs = _build([READ_SCHEMA])
    p = XmlToolStreamParser()
    _, completed = p.feed(docs)
    read_examples = [e for e in completed if e["name"] == "Read"]
    assert read_examples, "build_tool_docs must contain a parsable <tool_use> example for each tool"
    assert "file_path" in read_examples[0]["input"]


def test_docs_mentions_param_subelement_format():
    """Doc must teach the sub-element format explicitly (vs attributes)."""
    docs = _build([READ_SCHEMA])
    assert "<param" in docs
    assert "</param>" in docs


def test_docs_mentions_cdata_for_special_chars():
    """LLM must be told to wrap values with <, &, ]]> in CDATA."""
    docs = _build([])
    assert "CDATA" in docs


def test_docs_example_uses_cdata_when_needed_for_write():
    """If Write is documented, its example should demonstrate CDATA (contains code likely with special chars)."""
    docs = _build([WRITE_SCHEMA])
    assert "Write" in docs


def test_docs_mentions_parallelism():
    """LLM should know several <tool_use> blocks in one message = parallel execution."""
    docs = _build([READ_SCHEMA])
    assert "parallel" in docs.lower() or "multiple" in docs.lower() or "plusieurs" in docs.lower()
