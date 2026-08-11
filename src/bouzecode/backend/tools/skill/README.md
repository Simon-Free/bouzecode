# tools/skill/

## Purpose
Skills are reusable prompt templates stored as markdown files with YAML frontmatter. This
folder finds them, decides which one wins when several answer to the same name, and exposes
them to the model as the `Skill`, `SkillList` and `SkillGrep` tools.

## Usage
- `loader.py` — `SkillDef` (the dataclass carrying name/triggers/tools/prompt/scope), `load_skills`, `resolve_skills`, `find_skill`, `register_builtin_skill`. `_get_skill_paths` orders the stores; `_project_skill_dirs` walks `cwd` and its ancestors up to the home directory so a nested project also sees the skills filed higher in the tree; `_iter_skill_files` accepts both a flat `<store>/<name>.md` and a nested `<store>/<name>/skill.md`
- `scope.py` — *where a skill applies*, as opposed to where its file lives: `implicit_scope_for_file`, `resolve_declared_scope`, `scope_anchors` (adds the main repo root when running inside a linked git worktree), `covers`, `specificity`, `resolve` → `SkillResolution` (`winners`, `shadowed`, `ambiguous`), `report_shadows`. Deepest scope wins; storage rank only breaks ties
- `parsing.py` — `_parse_skill_file` (one markdown file → `SkillDef`; a malformed file is refused whole and reported on stderr, never half-loaded), `_parse_list_field`, `substitute_arguments` (`$ARGUMENTS` and positional `$ARG_NAME`)
- `frontmatter.py` — `split_frontmatter`, `closing_delimiter_index`, `parse_frontmatter_fields`, `UnterminatedFrontmatterError`. The delimiter is a LINE equal to `---`, never a substring, so a table separator in the body cannot be mistaken for the closing fence
- `tools.py` — the three registered tools: `Skill` (renders a skill's prompt inline, refuses to arbitrate an ambiguous name), `SkillList` (winners plus a `Masquées` section naming every shadowed file), `SkillGrep` (regex over the raw `.md` content, frontmatter included). All three honour a `_profile_skills` filter carried in `config`
- `builtin.py` — `_register_builtins()`: the skills that ship with the package (`python-coding`, `fast-testing`, `commit`, `review`) and their prompt bodies
- `__init__.py` re-exports the public surface and imports `builtin` for its registration side effect
