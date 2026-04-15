# ui/

## Purpose
Terminal rendering primitives for the REPL: ANSI colors, streaming text with Rich Live, spinners, and tool-call display.

## Usage
- `ansi.py` — `C` color dict, `clr()`, `info()`, `ok()`, `warn()`, `err()`
- `rendering.py` — `stream_text()`, `stream_thinking()`, `flush_response()`, module globals `_RICH`, `_RICH_LIVE`, `console`, `_accumulated_text`
- `spinner.py` — `_start_tool_spinner()`, `_stop_tool_spinner()`, `_change_spinner_phrase()`, `_spinner_lock`, `_spinner_phrase`
- `tool_display.py` — `print_tool_start()`, `print_tool_end()`, `render_diff()`, `_fmt_duration()`, `_last_diffs`
