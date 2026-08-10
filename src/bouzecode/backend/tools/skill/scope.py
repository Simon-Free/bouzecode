# [desc] Skill SCOPE: the directory tree a skill applies to, and the most-specific-wins resolution that makes shadowing visible instead of silent. [/desc]
"""Skill scope — *where a skill applies*, as opposed to *where a skill is stored*.

Storage location (`~/.bouzecode/skills`, `<projet>/.bouzecode/skills`, an `--extra-dir`)
answers "where does this file live". Scope answers "which agents does it concern". They
are not the same axis, and conflating them is why, in a monorepo, every skill polluted
every agent.

A skill filed under ``<X>/.bouzecode/skills/`` or ``<X>/.claude/skills/`` implicitly
applies to ``<X>`` **and nowhere else** — that is already what an author means by putting
it there. A skill in a global store (``~/.bouzecode/skills``, ``~/.claude/skills``, an
extra dir) keeps applying everywhere, exactly as before. Any skill can override the
deduction with an explicit ``scope:`` frontmatter field (relative paths resolve from the
skill file's own directory, so a project skill travels with its repo).

Same-named skills are resolved **most specific first**: the deepest scope wins, storage
priority only breaks ties. Losers are *shadowed*, never silently dropped — they are
reported on stderr once each and listed by ``SkillList()``.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

SCOPE_SEPARATOR = ":"

# Storage priority, used only to break a tie between two skills of equal specificity.
# Mirrors the order _get_skill_paths() has always returned.
_SOURCE_RANK = {"extra": 4, "project": 3, "user": 2, "claude": 1, "builtin": 0}
_DEFAULT_RANK = _SOURCE_RANK["user"]

_SKILL_STORE_PARENTS = (".bouzecode", ".claude")


def global_stores() -> set[Path]:
    """The two per-user stores that stay GLOBAL: scope is never deduced for them.

    Main safety rail of the feature — deducing a scope for ``~/.bouzecode/skills`` would
    make 25 skills vanish at once.
    """
    from ...core.config import CONFIG_DIR
    return {(CONFIG_DIR / "skills").resolve(), (Path.home() / ".claude" / "skills").resolve()}


def implicit_scope_for_file(path: Path) -> str:
    """Scope deduced from where the skill file sits, or "" when it is global.

    Walks up to the enclosing ``skills`` store, so both layouts work: a flat
    ``<store>/name.md`` and a nested ``<store>/name/skill.md``.
    """
    stores = global_stores()
    for parent in path.resolve().parents:
        if parent.name != "skills":
            continue
        if parent in stores:
            return ""
        if parent.parent.name in _SKILL_STORE_PARENTS:
            return str(parent.parent.parent)
        return ""
    return ""


def resolve_declared_scope(declared: str, path: Path) -> str:
    """Turn an explicit ``scope:`` field into an absolute path (relative = from the file)."""
    declared = (declared or "").strip().strip('"').strip("'")
    if not declared:
        return ""
    candidate = Path(declared).expanduser()
    if not candidate.is_absolute():
        candidate = path.resolve().parent / candidate
    return str(Path(candidate).resolve())


def scope_anchors(cwd: Path) -> list[Path]:
    """Directories a scope may cover for this agent to be in scope.

    Normally just the cwd. In a LINKED GIT WORKTREE — the project's dominant execution
    mode, one worktree per ticket — the main repo root is added too, so a skill whose
    scope was written as an absolute path to the main checkout still applies.
    """
    resolved = Path(cwd).resolve()
    anchors = [resolved]
    main_root = _main_worktree_root(resolved)
    if main_root is not None and main_root not in anchors:
        anchors.append(main_root)
    return anchors


def _main_worktree_root(cwd: Path) -> Path | None:
    """Main repo root when `cwd` is inside a linked worktree, else None.

    A linked worktree's ``.git`` is a FILE holding ``gitdir: <main>/.git/worktrees/<n>``.
    Read it directly rather than shelling out to `git rev-parse`: no subprocess on a path
    walked at every skill load.
    """
    for base in [cwd, *cwd.parents]:
        marker = base / ".git"
        if marker.is_dir():
            return None
        if not marker.is_file():
            continue
        pointer = marker.read_text(encoding="utf-8", errors="replace").strip()
        if not pointer.startswith("gitdir:"):
            return None
        gitdir = Path(pointer.split(":", 1)[1].strip())
        if gitdir.name and gitdir.parent.name == "worktrees":
            return gitdir.parent.parent.parent.resolve()
        return None
    return None


def covers(scope: str, anchors: list[Path]) -> bool:
    """True when one of the agent's anchor directories sits inside `scope`."""
    if not scope:
        return True
    root = Path(scope)
    return any(anchor == root or root in anchor.parents for anchor in anchors)


def specificity(scope: str) -> int:
    """How narrow a scope is. Global (no scope) is the least specific of all."""
    return len(Path(scope).parts) if scope else -1


def sort_key(skill) -> tuple[int, int]:
    return specificity(skill.scope), _SOURCE_RANK.get(skill.source, _DEFAULT_RANK)


@dataclass
class SkillResolution:
    """Outcome of resolving every candidate skill against one working directory."""
    winners: list = field(default_factory=list)
    shadowed: dict = field(default_factory=dict)   # name -> [SkillDef losing to the winner]
    ambiguous: set = field(default_factory=set)    # names no rule could arbitrate

    def by_name(self, wanted: str):
        """Look a skill up by its plain name OR its `label:name` qualified form."""
        for skill in self.winners:
            if skill.name == wanted or (skill.qualified_name and skill.qualified_name == wanted):
                return skill
        return None

    def candidates_for(self, name: str) -> list:
        """Every in-scope skill answering to `name`, winner first."""
        winner = self.by_name(name)
        return ([winner] if winner else []) + list(self.shadowed.get(name, []))


def resolve(candidates: list, cwd: Path) -> SkillResolution:
    """Filter by scope, then pick a winner per name: most specific first.

    `candidates` is ordered lowest-priority-first (the historical load order); the
    returned winners keep that order so callers that iterate skills see no reshuffle.
    """
    anchors = scope_anchors(cwd)
    for skill in candidates:
        skill.qualified_name = ""
    in_scope = [s for s in candidates if covers(s.scope, anchors)]
    # Highest priority first, then a STABLE sort by decreasing specificity: equal keys
    # keep storage order, which reproduces the historical "highest priority wins".
    ordered = sorted(reversed(in_scope), key=sort_key, reverse=True)

    best: dict[str, object] = {}
    shadowed: dict[str, list] = {}
    ambiguous: set[str] = set()
    for skill in ordered:
        incumbent = best.get(skill.name)
        if incumbent is None:
            best[skill.name] = skill
            continue
        shadowed.setdefault(skill.name, []).append(skill)
        if sort_key(skill) == sort_key(incumbent) and skill.scope != incumbent.scope:
            ambiguous.add(skill.name)

    for name, winner in best.items():
        if shadowed.get(name) and winner.scope:
            winner.qualified_name = f"{winner.scope_label}{SCOPE_SEPARATOR}{name}"
    winners = [s for s in in_scope if best.get(s.name) is s]
    return SkillResolution(winners=winners, shadowed=shadowed, ambiguous=ambiguous)


_REPORTED_SHADOWS: set[tuple[str, str, str]] = set()


def report_shadows(resolution: SkillResolution) -> None:
    """One stderr line per newly observed shadowing. Costs zero context tokens.

    Deduplicated for the life of the process: skills are reloaded several times per tool
    call, and a warning repeated 40 times is a warning nobody reads.
    """
    for name in sorted(resolution.shadowed):
        winner = resolution.by_name(name)
        for loser in resolution.shadowed[name]:
            key = (name, winner.file_path, loser.file_path)
            if key in _REPORTED_SHADOWS:
                continue
            _REPORTED_SHADOWS.add(key)
            print(f"[skill] '{name}' ({loser.file_path}) masquée par ({winner.file_path})",
                  file=sys.stderr)
