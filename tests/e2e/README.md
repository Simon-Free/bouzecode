# tests/e2e/

## Purpose
Feature tests for the four user-facing subsystems reached through tool calls:
plugins, skills, tasks and memory. Each test scripts a `MockLLM` with raw XML
`<tool_use>` turns and runs it through `tests.e2e_harness.bouzecode()`, so the real
registry, tool execution and turn loop run end to end with no network. Every store
(user and project scope) is repointed at `tmp_path`, and the classes carry
`@pytest.mark.backend`.

## Usage
- `test_plugin_e2e.py` — an empty plugin store loads nothing; a real plugin directory declared in an isolated user `plugins.json` is discovered by `list_plugins()` / `register_plugin_tools()` and its tool becomes callable; a registered plugin tool is then invoked by the model.
- `test_skill_e2e.py` — `Skill(name=…, args=…)` renders a project skill file with its argument substituted, and an unknown name comes back as an error the model can read.
- `test_task_e2e.py` — `TaskCreate` then `TaskList`, and the create-to-done lifecycle through `TaskUpdate`, against a reset task store.
- `test_memory_e2e.py` — `MemorySave` then `MemoryList`, and the saved memory really lands as a `.md` file in the project memory directory.
