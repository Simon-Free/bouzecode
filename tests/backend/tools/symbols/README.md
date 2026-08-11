# tools/symbols/

## Purpose

Covers symbol-aware reading: `bouzecode.backend.tools.folder_desc.symbols`
(`extract_symbols`, `find_symbol`), the `symbol=` path of
`tools.ops.file_ops._read`, and the symbol lines that `_get_folder_description` puts in
a folder listing.

Three approaches: direct calls on temporary source trees, config invariants read from
static data (`tools.schemas.TOOL_SCHEMAS`, the default profile loaded by
`load_profiles_from_dir`, `build_tool_docs`), and conversation tests through the
`bouzecode()` harness with `MockLLM`.

## Usage

- `test_symbols.py` — `extract_symbols` and `find_symbol` on Python sources, `Read` with
  a `symbol` filter, and the symbols shown by the folder description.
- `test_symbols_feature.py` — the same surface across languages (Python, JS, TS) plus
  the tool schema wiring.
- `test_symbols_e2e.py` — `Read(symbol=)` and `GetFolderDescription` driven by a mocked
  model through a full conversation.
- `test_symbols_schema.py` — discoverability: the `symbol` param appears in the Read
  schema, in the default profile's system-prompt extra, and in the XML tool docs.
- `test_symbol_not_found_message.py` — an unknown symbol makes `_read` list the symbols
  the file actually defines.
