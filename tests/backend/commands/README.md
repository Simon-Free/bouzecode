# commands/

## Purpose
Tests of the slash-command layer under `bouzecode.backend.commands` and of the CLI
flags that share its wiring. Approach: call the handler directly against a temporary
project dir, with `monkeypatch` for the few globals (config paths, stdin, the profile
resolver) — no mocking library, no LLM, no network.

## Usage
- `test_agent_switch.py` — `commands.extensions.agent_switch.cmd_agent`: listing built-in and profile agents in two sections, switching typology (tools, model, system prompt, preloaded profile skills), reverting to defaults, unknown and deferred names, and `install` writing a local yaml or surfacing plugin errors.
- `test_agent_upgrade.py` — `commands.agent_upgrade._plugins_to_upgrade`: dedup across profiles, single-agent selection, unknown name listing the available ones.
- `test_lazy_imports.py` — walks the AST of every module under `src/bouzecode/backend/commands/`, collects the imports written inside function bodies, and imports each one, parametrized per statement.
- `test_profile_skills_wiring.py` — `--profile <name>` in `bouzecode.ui.cli` preloads the profile's declared skills, and sets nothing for a profile without skills or an unknown one.
- `test_session_resume.py` — `commands.session.session_pick` / `session_resume` over a temporary daily dir: newest first, paging to older sessions, restoring the pick, out-of-range input.

## Subfolders
| Folder | Description |
|--------|-------------|
| `info/` | The read-only informational commands (`/history`, `/doctor`). |
