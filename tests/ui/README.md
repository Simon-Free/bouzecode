# tests/ui/

## Purpose
Tests for `bouzecode.ui`, the terminal layer: argument parsing at the entrypoint,
what is printed while a turn streams, and the paste-input widget. Nothing here talks
to a model; the units under test are pure rendering and parsing functions, driven
with captured stdout or a fake terminal.

## Usage
- No test module sits at this level; every test lives in a subfolder below.

## Subfolders
| Folder | Description |
|--------|-------------|
| `cli/` | The `bouzecode` entrypoint: which flag combinations reach the repl, and input sanitisation before a message is sent. |
| `display/` | What the terminal shows: tool call rendering, diff collapsing, streaming overflow, replay, and the spinner. |
| `paste_input/` | The paste badge model of the input line: segments, badge labels, display length. |
