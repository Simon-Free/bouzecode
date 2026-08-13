# ui/paste_input/

## Purpose
The prompt input line: multi-line editing on `prompt_toolkit`, where a multi-line paste
collapses into a single dimmed badge in the buffer and is expanded back to its full text on
submission.

## Usage
- `__init__.py` — `read_input_with_paste_blocks` (the main REPL entry point; falls back to plain `input()` when stdin is not a tty), `read_answer_with_paste_blocks` (same badges for prompts raised outside the REPL loop — AskUserQuestion choices, slash-command menus, permission prompts — with its own history so one-key answers stay out of the REPL history), `expand_paste_blocks`, `add_history`, `get_history`, `PASTE_BADGE_THRESHOLD`. Key bindings: Enter submits, Alt+Enter inserts a newline, a bracketed paste of at least the threshold in lines becomes a placeholder registered in `_pending`, and Backspace right after a badge deletes it whole. `_BadgeProcessor` styles the placeholders in the buffer
- `segments.py` — `paste_badge_label` (`line1 (+42 lines)`, first line truncated at 40 characters), `PastedBlock` (holds the full text behind a badge, with `display_text` / `plain_text` / `display_len`), `TextSegment`
