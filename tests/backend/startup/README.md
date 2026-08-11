# startup/

## Purpose

Covers what the process discovers when it starts: the extra-directory registry
(`bouzecode.backend.core.paths`), the auto-detection of a `.bouzecode/` folder in the current
directory, and the `LoadProjectConfig` tool (`backend.tools.ops.project_config`). Unit tests
over temporary trees, plus two conversation tests that check the discovered material actually
reaches the model.

## Usage

- `test_paths.py` — `get_extra_dirs`, `add_extra_dir`, `register_extra_dirs`: empty by default,
  registration replaces the previous set, empty strings filtered, the getter returns a copy.
- `test_auto_load_bouzecode.py` — a `.bouzecode/` directory in the current directory is
  registered at startup; absent, nothing is added; an explicit extra dir is not duplicated.
- `test_project_config.py` — `_load_project_config` and `_extract_skill_description` over a
  temp project: no folder, empty folder, skills, MCP config (including malformed JSON), plugins,
  hooks, cumulative calls, already-registered directory.
- `test_extra_dirs_e2e.py` — `TestExtraDirSkillsE2E`: a skill living in an extra dir is found by
  `skill.loader.load_skills` and takes precedence over the project one.
- `test_auto_load_bouzecode_e2e.py` — conversations via `tests.e2e_harness.bouzecode` and
  `MockLLM`: an auto-loaded project skill shows up in `build_system_prompt_parts` and through
  `SkillList`, `LoadProjectConfig` injects one into the next turn, a missing folder reports an error.
- `test_package_import.py` — the `bouzecode` package, `core.config`, `core.tool_registry`,
  `commands.session.revert_cmd` and `checkpoint.store` all import.
