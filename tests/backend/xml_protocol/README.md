# tests/backend/xml_protocol/

## Purpose

Covers the `bouzecode.backend.xml_tool_protocol` package at its edges: the serializer
(`serialize_tool_call`, `serialize_tool_result`), the system-prompt generator
(`build_tool_docs`), the `<tool_result>` filtering done by `XmlToolStreamParser`, and
the same protocol seen from a whole conversation.

Two approaches sit side by side. Unit files call the production functions directly and
round-trip their output back through the parser. The `_e2e` files run the real agent
loop through the `bouzecode()` harness — `MockLLM` for scripted turns, `mock_api` for
genuine SSE fragmentation — and assert on the resulting messages.

## Usage

- `test_xml_serializer.py` — serialization of calls and results: CDATA only where the
  value needs it, `token` attribute on results, and parse round-trips for code, regexes
  and shell quoting.
- `test_xml_docs.py` — `build_tool_docs` names every tool, lists its params, shows a
  parsable example, and never emits text the parser would take for a broken call.
- `test_xml_parser_tool_result.py` — `<tool_result>` blocks are stripped from parser
  output, including across chunks, without disturbing `<tool_use>` or `<thinking>`.
- `test_spaces_in_path.py` — paths containing spaces survive both layers: `_scan_params`
  and `_unwrap_cdata` in the parser, then `_write`/`_read`/`_edit` in `tools.ops.file_ops`.
- `test_depends_on_quoting_e2e.py` — conversation proof that a `depends_on` written with
  quoted brackets runs, that prose mentioning `<tool_use>` costs no error round-trip, and
  that a stream cut mid-call is reported instead of executed.
- `test_xml_stream_e2e.py` — the same parser invariants end to end over real SSE deltas
  (fragmentation, CDATA, fence and thinking shielding, truncation). Skipped on win32.

## Subfolders

| Folder | Description |
|--------|-------------|
| `parser/` | Unit coverage of `XmlToolStreamParser` itself: chunking, shielding, malformed input, recovery. |
