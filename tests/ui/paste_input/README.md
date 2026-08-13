# tests/ui/paste_input/

## Purpose
Covers the badge model of the input line (`bouzecode.ui.paste_input.segments`): a
multi-line paste collapses into a one-line badge instead of flooding the prompt.
Pure unit tests on the segment objects, no terminal and no rendering engine.

## Usage
- `test_badge_model.py` — `TextSegment` and `PastedBlock` display/plain text and display length (ANSI codes excluded), and `paste_badge_label` line counting plus long-first-line truncation.
- `test_bracketed_paste.py` — feeds bracketed-paste sequences into a real `PromptSession`: the buffer shows one collapsed badge line while the submitted result carries the full multi-line text. Also proves `ask_input_interactive` — the prompt behind AskUserQuestion choices and slash-command menus — returns a pasted block whole instead of one line per newline, and keeps its answers out of the main REPL history.
