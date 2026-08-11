# tools/folder_desc/

## Purpose
Inline `[desc]` one-liners kept at the top of source files, and the `GetFolderDescription`
tool that prints a folder tree combining those descriptions with a symbol outline. Also the
repo's symbol extractor, used by Read, Edit and the code maps.

## Usage
- `symbols.py` — `Symbol` (name, kind, docstring, `start_line`, `end_line`, `children`), `extract_symbols` (Python via `ast`, JS/TS/JSX/TSX via tree-sitter when installed, else empty), `find_symbol` returning a 1-based inclusive `(start, end)` for `name` or `Class.method`
- `desc_utils.py` — the `[desc] … [/desc]` comment format: `COMMENT_STYLES`, `EXT_TO_STYLE`, `wrap_description`, `extract_description` (searched in the first 10 lines only), `_find_desc_line_range`, `_is_ignored` / `_batch_is_ignored` (always-skip set plus one `git check-ignore --stdin` call for the whole batch)
- `analyzer.py` — description generation: `_call_llm_for_description` (routed through the provider stack, degrades to `None` on any failure), `_collect_code_files`, `_analyze_files` and `_analyze_folder` (thread pool of 20, `tqdm` progress on stderr), `_count_files_with_description`
- `tools.py` — `_get_folder_description`, registered as `GetFolderDescription`: a depth-limited tree of files with their `[desc]` and, for Python and JS/TS, each symbol with its docstring and `[L<a>-<b>]` range; missing descriptions are generated first. `_install_write_hook` wraps the registered `Write` tool so `_maybe_update_desc` refreshes an existing `[desc]` in a background thread
