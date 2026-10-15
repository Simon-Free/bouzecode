# [desc] Guard: no skill of the repo may cite a file path that does not exist on disk. [/desc]
"""Une skill du dépôt ne doit jamais citer un fichier qui n'existe plus.

Les skills décrivent où trouver le code. Après la migration vers `src/`, une centaine
de chemins cités pointaient dans le vide et personne ne le voyait : rien ne les
surveillait.

Si ce test devient rouge, la réponse est de corriger le chemin dans la skill, jamais
d'élargir la liste d'exceptions.
"""
from __future__ import annotations

import os
import re
from functools import cache
from pathlib import Path
from typing import NamedTuple

REPO_ROOT = Path(__file__).resolve().parents[4]
SKILL_DIRS = [REPO_ROOT / ".bouzecode" / "skills", REPO_ROOT / ".claude" / "skills"]

IGNORED_DIRS = {".venv", ".venv-ui", "node_modules", "dist", ".git", "__pycache__",
                ".pytest_cache", ".ropeproject"}
# Agent worktrees are full copies of the repo: walking them multiplied the scan and let
# a citation "resolve" against another agent's copy instead of this tree.
IGNORED_SUBTREES = {".claude/worktrees", ".bouzecode/worktrees"}

# Only source/doc extensions: a skill citing `.json`/`.yaml` almost always names a
# RUNTIME file (session stores, state, generated profiles) that the repo never holds.
CITED_PATH_RE = re.compile(
    r"[~A-Za-z0-9_./\\-]*[/\\][~A-Za-z0-9_./\\-]*"
    r"\.(?:py|md|ts|tsx|js|html|ps1|sh)\b"
)
BARE_PY_RE = re.compile(r"`([A-Za-z0-9_]+\.py)`")

# Citations that name no file of this repo: URLs, runtime paths under the user's
# home (`~/.bouzecode/...`), shell variables, globs, and documentation placeholders.
PLACEHOLDER_PREFIXES = ("http", "~", "$", "/path/to", "path/to", "<", "chemin/")


class RepoIndex(NamedTuple):
    files: set[str]  # posix paths relative to the root
    tails: set[str]  # every part of a file path that follows one of its "/"
    names: set[str]  # bare file names


def repo_files() -> set[str]:
    """Every file of the repo, as posix paths relative to the root.

    Ignored directories are pruned BEFORE descending: filtering after an rglob still
    paid for walking every venv, node_modules and agent worktree.
    """
    found = set()
    for dirpath, dirnames, filenames in os.walk(REPO_ROOT):
        relative_dir = Path(dirpath).relative_to(REPO_ROOT).as_posix()
        prefix = "" if relative_dir == "." else relative_dir + "/"
        dirnames[:] = [name for name in dirnames if name not in IGNORED_DIRS
                       and prefix + name not in IGNORED_SUBTREES]
        # A linked worktree holds a `.git` FILE: ignored like the `.git` directory.
        found.update(prefix + name for name in filenames if name not in IGNORED_DIRS)
    return found


@cache
def repo_index() -> RepoIndex:
    """Built once per run: both tests share the same walk."""
    files = repo_files()
    tails = {path[slash + 1:] for path in files
             for slash, char in enumerate(path) if char == "/"}
    return RepoIndex(files, tails, {path.rsplit("/", 1)[-1] for path in files})


def skill_files() -> list[Path]:
    return [path for directory in SKILL_DIRS if directory.is_dir()
            for path in sorted(directory.rglob("*.md"))]


def is_resolvable(cited: str, skill: Path, index: RepoIndex) -> bool:
    """True when the cited path plausibly maps onto a real file of the repo."""
    cited = cited.replace("\\", "/").strip("./")
    if not cited or cited in index.files:
        return True
    if (skill.parent / cited).is_file():
        return True
    # A repo file ends with "/<cited>": the skill cites the trailing part of its path.
    if cited in index.tails:
        return True
    # Absolute path spelled out in full (a command line, typically) into this repo.
    if any(cited[slash + 1:] in index.files
           for slash, char in enumerate(cited) if char == "/"):
        return True
    return "/" not in cited and cited in index.names


def dead_references(skill: Path, index: RepoIndex) -> list[str]:
    text = skill.read_text(encoding="utf-8", errors="replace")
    dead, seen = [], set()
    for match in list(CITED_PATH_RE.finditer(text)) + list(BARE_PY_RE.finditer(text)):
        cited = match.group(1) if match.re is BARE_PY_RE else match.group(0)
        if cited in seen:
            continue
        seen.add(cited)
        if cited.startswith(PLACEHOLDER_PREFIXES) or "*" in cited:
            continue
        if not is_resolvable(cited, skill, index):
            dead.append(cited)
    return dead


def test_no_skill_cites_a_file_that_no_longer_exists():
    """Chaque chemin de fichier cité par une skill du dépôt existe encore sur le disque."""
    index = repo_index()

    report = []
    for skill in skill_files():
        dead = dead_references(skill, index)
        if dead:
            report.append(f"{skill.relative_to(REPO_ROOT).as_posix()}: " + ", ".join(dead))

    assert not report, (
        "Références mortes dans les skills (corriger la skill, pas ce test) :\n"
        + "\n".join(report)
    )


def test_the_guard_actually_sees_a_dead_reference(tmp_path):
    """Le garde repère bien un chemin inventé, et laisse passer un chemin réel."""
    skill = tmp_path / "demo.md"
    skill.write_text(
        "Voir `src/bouzecode/backend/tools/skill/loader.py` et "
        "`src/bouzecode/backend/tools/skill/disparu.py`.",
        encoding="utf-8",
    )

    assert dead_references(skill, repo_index()) == [
        "src/bouzecode/backend/tools/skill/disparu.py"
    ]
