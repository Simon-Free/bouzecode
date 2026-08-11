# tests/backend/xml_tool_protocol/

## Purpose

Guards one rule of `bouzecode.backend.xml_tool_protocol.parser`: backticks written
inside a `<thinking>` block must not be read as opening a code span, because that span
would extend past the real `<tool_use>` tags that follow and hide them.

Pure unit tests: `XmlToolStreamParser` is fed text directly (whole or chunked) and
finalized. No LLM, no network, no filesystem.

## Usage

- `test_thinking_backticks.py` — `TestThinkingBackticksDoNotSwallowTools` (unpaired,
  paired-across-boundary and fenced backticks in thinking; tools after them still parse;
  code protection outside thinking stays intact) and `TestThinkingBlockDetection`
  (a `<tool_use>` written inside thinking is not a call).
