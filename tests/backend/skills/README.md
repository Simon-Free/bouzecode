# skills/

## Purpose

Covers the skill subsystem: parsing and loading skill files (`bouzecode.backend.tools.skill`),
the guidance the loader injects into the system prompt (`backend.core.context.get_skills_section`),
and scope resolution — which skill a given working directory is entitled to. Unit tests build
skill stores under `tmp_path`; the scope and prompt files run real conversations through
`tests.e2e_harness.bouzecode` with a `MockLLM`.

## Usage

- `test_skills.py` — `skill.loader`: `_parse_skill_file`, `_parse_list_field`, `find_skill`,
  `SkillDef`, plus `load_skills` and `substitute_arguments`. Frontmatter fields, nested
  `skill.md`, flat and nested stores coexisting, a project skill overriding a builtin,
  trigger aliases, positional and named argument substitution.
- `test_skill_frontmatter_delimiter.py` — frontmatter closes only on a line that is exactly
  `---`, never on a `---` inside the body; one broken skill does not prevent the others loading.
- `test_skill_shadow_report.py` — `load_skills` announces on stderr which skill shadows which,
  says it once per load, and stays silent for a skill with no namesake.
- `test_skill_grep.py` — `skill.tools._grep_skills` over hand-built `SkillDef`s: matching lines
  reported, case sensitivity toggle, invalid regex, frontmatter included in the searched text.
- `test_skills_section.py` — the static section returned by `get_skills_section`: discovery via
  `SkillList`, load before acting, the `LoadProjectConfig` rule, and no skill listing inlined.
- `test_skill_loading_prompt.py` — the same section encourages loading, and the thinking prompt
  carries the skill-scanning rule.
- `test_skills_prompt_e2e.py` — conversation level: the skills guidance reaches the model's
  system prompt, and `Skill(name=)` returns a rendered body (unknown name, trigger alias,
  argument substitution).
- `test_skill_scope_e2e.py` — a project-scoped skill is served to an agent working in that
  project and invisible from another tree; a parent-directory scope covers subprojects; the
  narrower scope wins; `SkillList` names the shadowed skill with both paths.
- `test_skill_scope_worktree.py` — the same resolution inside a real linked git worktree, where
  a scope written as an absolute path to the main checkout must still apply; two equally
  specific scopes are refused rather than guessed. Self-skips without `git`.
