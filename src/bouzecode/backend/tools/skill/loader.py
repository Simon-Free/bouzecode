# [desc] Discovers skill files across storage locations and resolves which one wins per name, scope first. [/desc]
"""Skill loading: which skill files exist, and which one wins for a given name.

Parsing one file lives in parsing.py; deciding *where a skill applies* lives in scope.py.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# Re-exported: callers (and tests) have always imported these from loader.
from .parsing import _parse_list_field, _parse_skill_file, substitute_arguments  # noqa: F401
from .scope import SkillResolution, report_shadows, resolve


@dataclass
class SkillDef:
    name: str
    description: str
    triggers: list[str]          # ["/commit", "commit changes"]
    tools: list[str]             # ["Bash", "Read"]  (allowed-tools)
    prompt: str                  # full prompt body after frontmatter
    file_path: str
    # Enhanced fields
    when_to_use: str = ""        # when Claude should auto-invoke this skill
    argument_hint: str = ""      # e.g. "[branch] [description]"
    arguments: list[str] = field(default_factory=list)  # named arg names
    model: str = ""              # model override
    user_invocable: bool = True  # appears in /skills list
    context: str = "inline"      # "inline" or "fork" (fork = sub-agent)
    source: str = "user"         # "user", "project", "builtin"
    # Scope: the directory tree this skill applies to ("" = global). See scope.py.
    scope: str = ""
    scope_label: str = ""        # short prefix used when a name collides ("projet:nom")
    qualified_name: str = ""     # set by the resolver, only when the name really collides


# ── Directory paths ────────────────────────────────────────────────────────

def _project_skill_dirs(cwd: Path) -> list[tuple[Path, str]]:
    """`.bouzecode/skills` and `.claude/skills` of `cwd` and its ancestors, nearest first.

    Walking the ancestors is what makes a monorepo work: an agent in
    `monorepo/backend/` also sees the skills filed at `monorepo/`. The walk stops at the
    home directory — `~/.bouzecode/skills` is the GLOBAL store, not a project's.

    `<cwd>/.claude/skills` is read too. It was not, which is why the project's own
    `writing-bouzecode-tests` skill was referenced by other skills yet never loadable.
    """
    home = Path.home().resolve()
    start = Path(cwd).resolve()
    dirs: list[tuple[Path, str]] = []
    for base in [start, *start.parents]:
        if base == home:
            break
        dirs.append((base / ".bouzecode" / "skills", "project"))
        dirs.append((base / ".claude" / "skills", "project"))
    return dirs


def _get_skill_paths() -> list[tuple[Path, str]]:
    """Return (path, source_label) tuples ordered highest-priority first."""
    from ...core.paths import get_extra_dirs
    from ...core.config import CONFIG_DIR
    extra = [(d / "skills", "extra") for d in get_extra_dirs()]
    base = [
        (CONFIG_DIR / "skills", "user"),  # ~/.bouzecode/skills (global, editable from the UI)
        (Path.home() / ".claude" / "skills", "claude"),
    ]
    return extra + _project_skill_dirs(Path.cwd()) + base


def _iter_skill_files(skill_dir: Path):
    """Yield skill markdown files found in `skill_dir`.

    Supports both layouts:
    - flat:  <skill_dir>/<name>.md
    - nested: <skill_dir>/<name>/skill.md  (Claude Code convention; also accepts SKILL.md)
    """
    if not skill_dir.is_dir():
        return
    yield from sorted(skill_dir.glob("*.md"))
    for child in sorted(skill_dir.iterdir()):
        if not child.is_dir():
            continue
        found_index = False
        for candidate in (child / "skill.md", child / "SKILL.md"):
            if candidate.exists():
                yield candidate
                found_index = True
                break
        # Also yield other .md files in subdirectories (sub-skills)
        for md_file in sorted(child.glob("*.md")):
            if md_file.name.lower() not in ("skill.md",):
                yield md_file



# ── Registry of built-in skills (registered by builtin.py) ────────────────

_BUILTIN_SKILLS: list[SkillDef] = []


def register_builtin_skill(skill: SkillDef) -> None:
    _BUILTIN_SKILLS.append(skill)


# ── Load all skills ────────────────────────────────────────────────────────

def _collect_candidates(include_builtins: bool, cwd: Path) -> list[SkillDef]:
    """Every parseable skill, lowest storage priority first (the historical load order)."""
    candidates: list[SkillDef] = list(_BUILTIN_SKILLS) if include_builtins else []
    directories = _get_skill_paths()
    if cwd is not None:
        # An explicitly frozen cwd brings its own project trees along: _get_skill_paths()
        # only knows about Path.cwd().
        directories = _project_skill_dirs(cwd) + directories
    seen_dirs: set[Path] = set()
    ordered: list[tuple[Path, str]] = []
    for skill_dir, src in directories:
        resolved = Path(skill_dir).resolve()
        if resolved in seen_dirs:
            continue
        seen_dirs.add(resolved)
        ordered.append((skill_dir, src))
    for skill_dir, src in reversed(ordered):
        for md_file in _iter_skill_files(skill_dir):
            skill = _parse_skill_file(md_file, source=src)
            if skill:
                candidates.append(skill)
    return candidates


def resolve_skills(include_builtins: bool = True, cwd=None) -> SkillResolution:
    """Resolve skills against a working directory: winners, shadowed, ambiguous.

    `cwd` defaults to the process working directory. Pass it explicitly (frozen at agent
    start) so a session that changes directory does not see its skill set shift under it.
    """
    base = Path(cwd) if cwd is not None else Path.cwd()
    resolution = resolve(_collect_candidates(include_builtins, cwd), base)
    report_shadows(resolution)
    return resolution


def load_skills(include_builtins: bool = True, cwd=None) -> list[SkillDef]:
    """Return the skills in scope for `cwd`, one per name (most specific scope wins)."""
    return resolve_skills(include_builtins=include_builtins, cwd=cwd).winners


def find_skill(query: str, cwd=None) -> Optional[SkillDef]:
    """Find a skill by qualified name, or whose trigger matches the first word of query."""
    query = query.strip()
    if not query:
        return None

    first_word = query.split()[0]
    skills = load_skills(cwd=cwd)
    for skill in skills:
        if skill.qualified_name and first_word == skill.qualified_name:
            return skill
    for skill in skills:
        for trigger in skill.triggers:
            if first_word == trigger:
                return skill
            if trigger.startswith(first_word + " "):
                return skill
    return None
