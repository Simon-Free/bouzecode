# [desc] Guard: no skill of the repo may cite a file path that does not exist on disk. [/desc]
"""Une skill du dépôt ne doit jamais citer un fichier qui n'existe plus.

Les skills décrivent où trouver le code. Après la migration vers `src/`, une centaine
de chemins cités pointaient dans le vide et personne ne le voyait : rien ne les
surveillait. Ce garde joue pour les skills le rôle que `readme_sync --check` joue
pour les AGENTS.md.

Si ce test devient rouge, la réponse est de corriger le chemin dans la skill, jamais
d'élargir la liste d'exceptions.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
SKILL_DIRS = [REPO_ROOT / ".bouzecode" / "skills", REPO_ROOT / ".claude" / "skills"]

IGNORED_DIRS = {".venv", ".venv-ui", "node_modules", "dist", ".git", "__pycache__",
                ".pytest_cache", ".ropeproject"}

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


def repo_files() -> set[str]:
    """Every tracked-looking file of the repo, as posix paths relative to the root."""
    found = set()
    for path in REPO_ROOT.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(REPO_ROOT)
        if any(part in IGNORED_DIRS for part in relative.parts):
            continue
        found.add(relative.as_posix())
    return found


def skill_files() -> list[Path]:
    return [path for directory in SKILL_DIRS if directory.is_dir()
            for path in sorted(directory.rglob("*.md"))]


def is_resolvable(cited: str, skill: Path, files: set[str], names: set[str]) -> bool:
    """True when the cited path plausibly maps onto a real file of the repo."""
    cited = cited.replace("\\", "/").strip("./")
    if not cited or cited in files:
        return True
    if (skill.parent / cited).is_file():
        return True
    if any(path.endswith("/" + cited) for path in files):
        return True
    # Absolute path spelled out in full (a command line, typically) into this repo.
    if any(cited.endswith("/" + path) for path in files):
        return True
    return "/" not in cited and cited in names


def dead_references(skill: Path, files: set[str], names: set[str]) -> list[str]:
    text = skill.read_text(encoding="utf-8", errors="replace")
    dead, seen = [], set()
    for match in list(CITED_PATH_RE.finditer(text)) + list(BARE_PY_RE.finditer(text)):
        cited = match.group(1) if match.re is BARE_PY_RE else match.group(0)
        if cited in seen:
            continue
        seen.add(cited)
        if cited.startswith(PLACEHOLDER_PREFIXES) or "*" in cited:
            continue
        if not is_resolvable(cited, skill, files, names):
            dead.append(cited)
    return dead


def test_no_skill_cites_a_file_that_no_longer_exists():
    """Chaque chemin de fichier cité par une skill du dépôt existe encore sur le disque."""
    files = repo_files()
    names = {path.rsplit("/", 1)[-1] for path in files}

    report = []
    for skill in skill_files():
        dead = dead_references(skill, files, names)
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
    files = repo_files()
    names = {path.rsplit("/", 1)[-1] for path in files}

    assert dead_references(skill, files, names) == [
        "src/bouzecode/backend/tools/skill/disparu.py"
    ]
