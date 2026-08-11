# folder_desc/

## Purpose
Generates one-line `[desc] ... [/desc]` summaries for source files, stores them as a comment at the top of each file, and exposes a tool that aggregates them into a folder-level description.

## Usage
- `desc_utils.py` — `wrap_description()`, `extract_description()`, `COMMENT_STYLES`, `EXT_TO_STYLE` — per-language comment syntax, plus `_find_desc_line_range()` and `_is_ignored()` for locating an existing tag and skipping vendored/build directories
- `analyzer.py` — `_analyze_folder()`, `_collect_code_files()`, `_call_llm_for_description()` — walks a folder, describes files in a thread pool, and prepends the tag to each
- `tools.py` — registers the `GetFolderDescription` tool; `_install_write_hook()` and `_maybe_update_desc()` refresh a file's description in the background after it is written
