# commands/sentinels/

## Purpose
Reachability locks for the slash commands that answer with a *sentinel tuple* instead of
doing the work themselves: `/worker`, `/ssj`, `/image`. All three were imported by
`dispatcher.py` yet absent from `COMMANDS`, so they printed "Unknown command" — the
defect `/telegram` had. Each test drives `handle_slash`, the REPL's own entry point, and
asserts the tuple handed back, the command's real contract (`ui/repl_sentinels.py` acts
on it). No network, no process, no window: the clipboard and the menu's keyboard are
supplied as plain fakes, never `unittest.mock`.

## Usage
- `test_worker_is_reachable.py` — `/worker --path <tmp todo>` returns `("__worker__", tasks)` with one prompt per `- [ ]` line; `--tasks` / `--workers` narrow the batch; a bad selection or a missing file is handled without a sentinel.
- `test_ssj_is_reachable.py` — the menu's `ask_input_interactive` is replaced by a scripted reader: a typed slash returns `__ssj_passthrough__`, entry 3 returns `("__ssj_cmd__", "worker", …)`, entry 6 returns `__ssj_query__`, entry 0 returns `True`; every question is asked with the caller's own config object.
- `test_image_is_reachable.py` — a fake `PIL.ImageGrab` holds the clipboard: a capture returns `("__image__", prompt)` and leaves the base64 PNG on the caller's config; an empty clipboard is handled without a sentinel.

Each file also checks that its command appears in `/help` and that its handler takes the
three positional parameters `handle_slash` passes.
