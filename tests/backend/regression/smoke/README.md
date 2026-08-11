# regression/smoke/

## Purpose

Cheap whole-codebase checks that the package still starts and that every import written in
`src/` points at something real. Two AST sweeps over the source tree, plus direct imports, a
`py_compile`, a subprocess launch and a version comparison against the package metadata.

## Usage

- `test_import_targets_resolve.py` — AST sweep: every `bouzecode.*` import target, including
  the lazy ones written inside functions, resolves to a real module.
- `test_import_symbols_resolve.py` — every source file compiles, and every
  `from bouzecode.* import NAME` resolves to a real attribute or submodule.
- `test_repl_syntax.py` — `ui/repl.py` compiles, via `py_compile` on the file path.
- `test_repl_importable.py` — `bouzecode.ui.repl` imports and exposes `repl`.
- `test_main_module.py` — `python -m bouzecode --help` runs.
- `test_version.py`, `test_version_sync.py` — `ui.cli.VERSION` matches the version declared in
  the package metadata (`pyproject.toml`).
