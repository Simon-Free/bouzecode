# tests/backend/tools/

## Purpose

Root of the coverage for `bouzecode.backend.tools` — the tool implementations the agent
calls — plus the registry that exposes them. The files at this level hold what does not
belong to one specialised family: diff rendering, edit result shaping, folder
descriptions, the default enable whitelist, scratch files, the deferred queue, and the
registry-versus-overlay invariant.

Two approaches. Unit files import the production function (`_edit`, `_write`,
`generate_unified_diff`, `_get_folder_description`, ...) and drive it over a `tmp_path`
tree. Files suffixed `_e2e` run a whole conversation through the `bouzecode()` harness
with `MockLLM` and assert on the messages the agent produced.

## Usage

- `test_diff_view.py` — `generate_unified_diff` and `maybe_truncate_diff`, and the diff
  that `_edit`/`_write` return (a freshly created file returns none).
- `test_edit_compact_result.py` — `agent.loop_turn._compact_tool_result` strips the diff
  out of an Edit/Write result before it enters the state messages.
- `test_edit_enriched_result.py` — an Edit result carries surrounding context on success
  and a fuzzy match on failure; also checks Edit/Write snippetability through
  `agent.snippet_wire` and `build_minimal_payload`.
- `test_folder_desc.py` — `folder_desc.desc_utils._batch_is_ignored`,
  `folder_desc.analyzer._collect_code_files` (non-code and virtualenv pruning) and the
  tree format of `_get_folder_description`.
- `test_gfd_depth.py` — `GetFolderDescription` honours `max_depth` when walking.
- `test_default_disabled_tools.py` — what reaches the model is exactly the
  `registration._DEFAULT_ENABLED` whitelist; anything else answers "currently disabled".
- `test_mods.py` — the `lru_cache` on `_has_rg`, parallel tool execution, and the
  safeguards that warn when a file changed under the agent between read and edit.
- `test_scratch_temp.py` — `temp=True` on Write/Edit/Read puts files outside the git
  worktree, under the OS temp dir, and `tools.ops.scratch` cleanup destroys them.
- `test_glob_cap_e2e.py` — a Glob matching far more files than `GLOB_CAP` still
  succeeds: it prints the cap, reports the true total, and rolls the rest up by folder.
- `test_deferred_flow_e2e.py` — `Bash(deferred=True)` enqueues without executing, and a
  `FinalAnswer` with a non-empty queue raises `tools.interaction.DeferredChecks`.
- `test_removed_guards_e2e.py` — pins the behaviour around the grep/glob guard and the
  out-of-worktree path: root-scoped Grep and Glob return their matches, and a write
  outside the worktree happens and is never blocked.
- `test_overlay_preserves_global_registry.py` — a thread-local registry overlay must
  never strip the core tools from the global registry. Runs in a subprocess, because the
  faulty import order is unreachable once the worker has imported `registration`.

## Subfolders

| Folder | Description |
|--------|-------------|
| `ops/` | Output compaction and the leniency of Edit and Read parameters. |
| `registry/` | Tool registry, slash commands, enable/disable, output truncation. |
| `runner/` | The `RunPythonTest` tool and its progress reporting. |
| `search/` | Bash, Grep and Glob in `tools.ops.shell_search` and `tools.ops.bash_bg`. |
| `skill/` | Text invariants of the builtin skill prompts. |
| `symbols/` | Symbol extraction and symbol-aware Read / folder descriptions. |
