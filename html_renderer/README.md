# html_renderer/

## Purpose
Turns a recorded agent session into a single self-contained HTML page: the transcript is parsed into typed blocks, then rendered with per-tool cards, syntax-highlighted diffs and markdown formatting.

## Usage
- `parser.py` — `parse_session()`, `UserMessage`, `AssistantText`, `ToolCall`, `ToolResult`, `Block` — regex parsing of the `<tool_use>` / `<tool_result>` / `<param>` transcript markup
- `json_parser.py` — `parse_session_json()`, `strip_tool_xml()` — same block sequence built from a messages array instead of raw text
- `renderer.py` — `render_html()` — emits the page with inline CSS, tool icons and colors, `_render_diff()` for edits, `_md()` for markdown, and a session footer with token counts
- `demo.py` — `main()` writes `demo.html` from a hardcoded example session
- `__init__.py` re-exports the public surface
