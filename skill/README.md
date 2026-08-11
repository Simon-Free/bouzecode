# skill/

## Purpose
Skills are reusable prompt templates stored as markdown files with YAML frontmatter. This package discovers them, resolves their arguments, and runs them either inline in the current conversation or in a forked sub-agent.

## Usage
- `loader.py` — `SkillDef`, `load_skills()`, `find_skill()`, `substitute_arguments()`, `register_builtin_skill()` — searches project, user and `.claude` skill directories; `_parse_skill_file()` reads the frontmatter (triggers, allowed tools, model, `context: inline|fork`, argument names)
- `executor.py` — `execute_skill()` — dispatches to `_execute_inline()` (prepends the prompt to the current turn) or `_execute_forked()` (isolated sub-agent with the skill's tool and model restrictions)
- `builtin.py` — `_register_builtins()` registers the shipped `commit`, `review` and `fast-testing` skills
- `tools.py` — registers the `Skill`, `SkillList` and `SkillGrep` tools so the model can invoke, enumerate and search skills
- `__init__.py` re-exports the public surface and imports `builtin` to trigger registration
