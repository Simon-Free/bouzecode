# thinking/

## Purpose

Covers `bouzecode.backend.agent.thinking_parser` — the streaming split between the model's
reasoning and its answer — and the archiving of that reasoning into the saved assistant
message. Mostly pure unit tests that feed text to the parser; one conversation-level test
proves reasoning streamed by a provider survives to the transcript.

## Usage

- `test_thinking_parser.py` — `ThinkingStreamParser`, `LoopDetector`, `ThinkingDisciplineMonitor`,
  `strip_thinking_tags`, and `minimal_payload._strip_thinking_from_messages`: whole and chunked feeds.
- `test_thinking_parser_escape.py` — a `<thinking>` / `</thinking>` tag appearing mid-line is
  content, not a block delimiter.
- `test_thinking_indentation.py` — the column-0 close rule, checked on the parser, on
  `strip_thinking_tags`, and on `xml_tool_protocol.parser._is_in_thinking`.
- `test_thinking_pathological.py` — four hostile cases: close tag quoted inside the reasoning,
  tool XML inside a thought, consecutive thoughts, stream ending on an unclosed tag.
- `test_thinking_parser_pathological.py` — the same four cases fed both whole and in
  five-character chunks, comparing the concatenated stream events.
- `test_strip_tool_use.py` — `strip_tool_use_xml` on CDATA, backticks, and blocks mixed with
  thinking tags.
- `test_thinking_save.py` — `agent.loop._build_assistant_content` prepends the archived thinking
  to the content that gets saved.
- `test_thinking_stream_e2e.py` — a `mock_api` conversation through `tests.e2e_harness.bouzecode`:
  reasoning streamed as SSE `thinking_delta` is reassembled and archived, then stripped from the
  next turn's wire payload. Self-skips on Windows.

## Subfolders

| Folder | Description |
|--------|-------------|
| `overflow/` | The thinking-overflow budget: when a reasoning turn is cut, nudged, summarized and persisted. |
