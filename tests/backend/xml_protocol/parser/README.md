# xml_protocol/parser/

## Purpose

Unit coverage of `XmlToolStreamParser` in
`bouzecode.backend.xml_tool_protocol.parser`, the incremental parser that turns a text
stream into visible text plus completed tool calls.

All files drive the parser directly: build one, `feed()` it text in one shot or in
chunks of a chosen size, then `finalize()`, and split the interleaved result list into
strings (visible text) and dicts (calls). No LLM, no network, no filesystem. The rule
under test throughout is that a malformed block becomes an error call carrying a
diagnostic, never a silent drop.

## Usage

- `test_xml_parser.py` — the baseline surface: chunk splits at every position, CDATA,
  multiple and interleaved blocks, empty and unknown params, quote styles, newline
  handling around calls, `depends_on` bracket syntax, and the errors raised by an
  unclosed block, a malformed attribute or a missing `name`. Two tests carry the error
  onward through `core.tool_registry.execute_tool` and `agent._check_permission`.
- `test_xml_parser_backtick.py` — `<tool_use>` inside a triple-backtick fence or a
  double-backtick span is text, not a call; also exercises the helpers `_is_in_code`
  and `_has_unclosed_fence` directly.
- `test_xml_parser_single_backtick.py` — same rule for single-backtick spans and for
  space- or tab-indented code blocks.
- `test_xml_parser_thinking.py` — prose that mentions `<thinking>` must not suppress
  parsing; includes direct checks on `_is_in_thinking`.
- `test_xml_parser_thinking_backticks.py` — backticks inside a thinking block must not
  open a code span that swallows the tool calls after it, whole-text, chunked, and on
  replayed session shapes.
- `test_emission_avalee_regression.py` — the same swallowing failure stated as a
  regression, plus the hold buffer used while a thinking block streams.
- `test_literal_angles_in_param.py` — param values containing bare `<` and `>` without
  CDATA still parse, alone and combined with thinking.
- `test_xml_parser_quote_slip.py` — a param closed like an attribute (`">` instead of
  `</param>`) must cost only the broken call: the well-formed siblings in the batch are
  salvaged, the log names what broke, nominal streams stay untouched, and recovery never
  invents a call.
- `test_xml_parser_no_params.py` — a `<tool_use>` with a body but no `<param>` tag is an
  error, checked both through `feed()` and on `_parse_block`.
- `test_xml_parser_self_closing.py` — `<param ... />` with or without a `value`
  attribute is accepted, including split across chunks, and does not destroy the block
  that follows.
- `test_depends_on_and_prose_blocks.py` — the accepted spellings of `depends_on` and
  `tool_call_alias`, a nameless `<tool_use>` treated as prose, and truncated streams
  staying errors.
