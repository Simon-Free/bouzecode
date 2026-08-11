# regression/structure/

## Purpose

Locks on the shape of the repository: which package answers for which module, what the
packaging declares, and conventions that no single file can enforce alone. The approach is
import probes plus AST and disk sweeps over `src/` and over the repo's own metadata — no LLM,
no conversation.

## Usage

- `test_root_moved.py` — `core.config.load_config`, `core.context.build_system_prompt_parts`,
  `core.tool_registry`, `core.paths`, `agent.compaction.estimate_tokens`,
  `agent.minimal_payload.build_messages_for_api` and `agent.providers` answer at their package
  paths, the pre-move root paths do not, and `MODELS` lists only Anthropic models.
- `test_providers_moved.py` — `agent.providers` exports `stream`, the chunk and turn types and
  `MODELS`; `providers.backends.dispatch.stream` exists; `backend.agent` imports cleanly.
- `test_root_cleanup.py` — `backend.setup_tools` and the `backend.subagent` shim are not
  importable, and `agent.thinking_parser` answers only at its package path.
- `test_session_load_import.py` — `commands.session.session_load.cmd_load` imports.
- `test_no_mcp_references.py` — no file under the installed package imports `bouzecode.*mcp`.
- `test_display_helpers_are_not_wrapped.py` — `ui.ansi.info/ok/warn/err` print and return
  `None`, and no source file wraps one of them in `print()` (which would emit a bare `None`).
- `test_packaging_declarations.py` — the generated lockfile and the generated map locks are
  git-ignored, the test extra declares the timeout plugin, `tqdm` is a declared runtime
  dependency, and the timeout marker actually works.
- `test_powershell_launchers.py` — the shipped `.ps1` launchers are pure ASCII and load the
  dotenv file before installing any dependency.
- `test_skill_references.py` — no skill in the repo cites a file path absent from disk, plus a
  self-check that the guard really flags a planted dead reference.
- `test_test_packages_are_complete.py` — every directory holding tests is a package and the
  `__init__.py` chain reaches `tests/` without a hole, so no test module shadows another.
  Test names and docstrings are in French.
