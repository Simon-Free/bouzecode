# messages/

## Purpose
Wording the terminal prints to a human. English by default; French when
`BOUZECODE_LANG` starts with `fr` (`fr`, `fr_FR.UTF-8`, `fr-BE`, …).

Only user-facing terminal strings belong here. Comments, docstrings and anything
addressed to the model (system prompts, tool instructions) are out of scope.

## Usage
```python
from bouzecode.ui.messages import msg, terminal_language

print(f"\033[33m⚠ {msg('ripgrep.missing')}\033[0m")
msg("ripgrep.downloading", version="14.1.1")   # placeholders are keyword args
terminal_language()                            # "en" | "fr"
```
An unknown key raises `KeyError` on the spot. ANSI codes and glyphs stay at the call
site — the tables hold plain text.

## Files
| File | Description |
|------|-------------|
| `__init__.py` | `msg()` / `terminal_language()`, and the merged `MESSAGES` table |
| `terminal.py` | wording of the terminal UI itself (`ui/cli.py`, `ui/tool_display.py`) |
| `agents.py` | wording of the `/agent`, `/agent install` and `/agent-upgrade` commands |
