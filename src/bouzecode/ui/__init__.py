# [desc] Re-exports UI utilities: ANSI colors, rendering, spinner, and tool display functions. [/desc]
from .ansi import C, clr, info, ok, warn, err
from .rendering import (
    _accumulated_text, _current_live, _live_overflow, _overflow_lines_buf,
    _RICH_LIVE, _RICH, console,
    _make_renderable, _start_live, _estimate_rendered_lines, _erase_lines,
    _flush_overflow_line, stream_text, stream_thinking, flush_response,
)
from .spinner import (
    _TOOL_SPINNER_PHRASES, _DEBATE_SPINNER_PHRASES,
    _spinner_phrase, _spinner_lock,
    _run_tool_spinner, _start_tool_spinner, _change_spinner_phrase, _stop_tool_spinner,
)
from .tool_display import (
    render_diff, _has_diff, _last_diffs, _fmt_duration,
    print_tool_start, print_tool_end, _tool_desc,
)
try:
    from .replay import replay_messages
except ImportError:
    replay_messages = None  # graceful degradation if replay deps missing
