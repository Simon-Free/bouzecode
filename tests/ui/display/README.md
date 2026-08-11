# tests/ui/display/

## Purpose
Covers what the terminal shows during and after a turn: `ui.rendering`,
`ui.tool_display`, `ui.replay` and `ui.spinner`. The approach is capture, not
mocking of a model — the rendering helpers are called directly and their output is
read back from `capsys`, a `StringIO` console, or a fake terminal object.

## Usage
- `test_tool_display.py` — `_format_tool_call` renders a call verbatim in a multi-line block (every parameter, long values truncated, inline markup neutralized), and `_is_failure` classifies errors and synthetic error tools.
- `test_inline_tool_display.py` — `ToolCallParsed` and `ToolStart` fields, and the deduplication that suppresses a `ToolStart` line already shown inline while streaming.
- `test_live_overflow.py` — diffs stay collapsed in `print_tool_end` (summary plus hint, full diff stored for `/diff`), the `/diff` command listing and filtering, and the Rich Live overflow switch to direct printing above the height threshold.
- `test_render_tool_markup.py` — `_neutralize_tool_markup` and `_make_renderable` keep `<param>` tags visible through Rich Markdown instead of letting them be stripped.
- `test_replay.py` — `replay_messages` output for an empty conversation, text turns, internal and native tool blocks, inline tool XML stripping, and skipped tool-result messages.
- `test_no_animation_off_terminal.py` — `animation_enabled` and the tool spinner: frames on a terminal, none on a pipe, so `-p` output stays pipeable.
