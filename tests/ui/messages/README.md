# tests/ui/messages/

## Purpose
Covers `bouzecode.ui.messages`: the terminal answers in English by default and in
French when `BOUZECODE_LANG` asks for it. The resolver is exercised through its public
surface (`msg`, `terminal_language`) and through a real command on its real output
path; no `unittest.mock`.

## Usage
- `test_terminal_language.py` — English by default, `BOUZECODE_LANG=fr` (and every spelling of it) switches to the wording the terminal used to print, an unknown value falls back to English, an unknown key raises, and no catalogue entry is left half-translated.
