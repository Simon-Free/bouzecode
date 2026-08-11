# runtime/html_renderer/

## Purpose
Turns a saved session — either raw transcript text or the JSON messages array —
into a sequence of typed blocks, then into one self-contained HTML page with
inline CSS, collapsible tool loops and diff views.

## Usage
- `parser.py` — `parse_session()`, `UserMessage`, `AssistantText`, `ToolCall`, `ToolResult`, `SystemNotice`, `Block` — splits raw text on `<tool_use>` / `<tool_result>` markers (ignoring those inside a thinking block) and strips CDATA from parameters.
- `json_parser.py` — `parse_session_json()`, `strip_tool_xml()` — same block sequence from the messages array, pairing results with calls by id, routing enforcement and system-event messages to `SystemNotice`, and dropping parse-error pseudo-tools.
- `renderer.py` — `render_html()` — the orchestrator: page head, session metadata, first-in-first-out pairing of results to calls, tool-loop grouping, thinking segments, spinner when unfinished, footer and diff bootstrap script.
- `blocks.py` — `_render_tool_block()`, `_render_plan_block()`, `_render_turn_stats_bar()`, `_render_session_footer()`, `_format_params()`, `_format_result()`, `_params_table()`, `_tool_summary_hint()`, `_identify_tool_groups()`, `_fmt_tok()` — per-block HTML, including the one-line summary shown on a collapsed tool.
- `markdown.py` — `_md()`, `_md_table()`, `_guess_language()`, `_json_script_safe()` — headings, bold, inline code, fenced blocks, lists and pipe tables.
- `diff.py` — `_render_diff()`, `_render_diff_text()` — a diff container with a unified-text fallback inside it.
- `constants.py` — `_CSS`, `_CTX_BAR_CSS`, `_TOOL_ICONS`, `_TOOL_COLORS`, `_DEFAULT_COLOR`, `_LANG_MAP`, `_SPINNER_HTML`, `_SPINNER_STYLE`, `_MONACO_INIT_SCRIPT`, `_THINKING_RE` — the static assets embedded in the page.
- `__init__.py` re-exports the public surface (`parse_session`, `parse_session_json`, `render_html`, `strip_tool_xml`, the block types).
