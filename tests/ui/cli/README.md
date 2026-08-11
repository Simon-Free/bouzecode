# tests/ui/cli/

## Purpose
Covers `bouzecode.ui.cli`: the argument guard that decides whether `main()` boots the
repl or exits, and the sanitisation applied to user input before it reaches the
provider SDK. `main()` is driven for real with `monkeypatch` on `sys.argv` and a
stubbed repl entrypoint; no `unittest.mock`.

## Usage
- `test_resume_deferred_prompt_guard.py` — `-p --resume-deferred <error>` boots into the repl with no positional prompt, while a bare `-p` still raises `SystemExit`.
- `test_surrogate_strip.py` — `strip_unpaired_surrogates` recombines valid UTF-16 surrogate pairs and drops orphaned ones, so every result encodes to UTF-8 without raising.
