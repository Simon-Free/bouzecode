# xml_tool_protocol

## Purpose

Bypass the SNCF `socle` proxy's mishandling of native Anthropic `tool_use` SSE blocks. The LLM emits tool calls as XML embedded in its text response; this package parses them locally and serializes them back for multi-turn history. Used only on the Anthropic provider path; OpenAI/Ollama keep native tool-calling.

## Usage

```python
from xml_tool_protocol import (
    XmlToolStreamParser, serialize_tool_call, serialize_tool_result, build_tool_docs,
)

parser = XmlToolStreamParser()
visible_text, completed_calls = parser.feed(stream_chunk)
# ...at end of stream:
trailing_errors = parser.finalize()

# Re-serialize history for the next API turn:
xml = serialize_tool_call({"id": "r1", "name": "Read", "input": {"file_path": "a.py"}})
xml = serialize_tool_result("r1", "file contents...")

# System-prompt section taught to the model:
prompt_section = build_tool_docs(tool_schemas)
```

Parse errors (unclosed block, malformed attributes, missing `name`) become `_XmlParseError` tool calls — never silently dropped — so the model receives a diagnostic via `tool_result` and can correct its next turn.
