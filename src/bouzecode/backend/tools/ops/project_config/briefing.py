# [desc] Rend le briefing d'un projet : nombre de skills, outils branchés, comment parcourir son code. [/desc]
"""Ce qu'un dossier équipé apporte, en quelques lignes.

Les skills ne sont plus listées : 26 lignes de description pesaient ~4,6 k car. à
chaque chargement de projet, payées même quand aucune ne servait. Le briefing dit
seulement combien il y en a ; `SkillResearch(query=...)` les trouve par mots-clés,
`Skill(name=...)` les ouvre.
"""
from __future__ import annotations

from bouzecode.paths import project_dir as bouzecode_project_dir
import json
from pathlib import Path


def project_skills(root: Path) -> list:
    """Les skills du `.bouzecode/skills` de ce dossier, dans l'ordre alphabétique."""
    from ...skill.loader import _iter_skill_files
    from ...skill.parsing import _parse_skill_file

    skills_dir = bouzecode_project_dir(root) / "skills"
    if not skills_dir.is_dir():
        return []
    parsed = [_parse_skill_file(f, source="project") for f in _iter_skill_files(skills_dir)]
    return sorted((s for s in parsed if s is not None), key=lambda s: s.name)


def project_plugins(root: Path) -> list[dict]:
    """Les manifestes des plugins du dossier (`plugin.json` de chaque sous-dossier)."""
    plugins_dir = bouzecode_project_dir(root) / "plugins"
    if not plugins_dir.is_dir():
        return []
    manifests = []
    for child in sorted(plugins_dir.iterdir()):
        manifest = child / "plugin.json"
        if manifest.is_file():
            manifests.append(json.loads(manifest.read_text(encoding="utf-8")))
    return manifests


def equipment_summary(root: Path) -> str:
    """Résumé d'une ligne de ce qu'un dossier apporte — sert à choisir entre enfants."""
    parts = []
    skills = project_skills(root)
    if skills:
        parts.append(f"{len(skills)} skill{'s' if len(skills) > 1 else ''}")
    plugins = project_plugins(root)
    if plugins:
        parts.append(f"{len(plugins)} plugin{'s' if len(plugins) > 1 else ''}")
    return ", ".join(parts) or "rien d'équipé"


def skills_block(root: Path) -> list[str]:
    skills = project_skills(root)
    if not skills:
        return ["## Skills (0) — ce projet n'en déclare aucune"]
    pluriel = "s" if len(skills) > 1 else ""
    return [f"## Skills ({len(skills)}) — {len(skills)} skill{pluriel} de projet disponible{pluriel} : "
            'trouve-les avec SkillResearch(query="<mots-clés>"), ouvre avec Skill(name=...)']


def plugins_block(wired: list[str], failures: list[str]) -> list[str]:
    """Les outils réellement branchés — pas ceux qu'un manifeste promet.

    Annoncer un outil qui n'est pas appelable est pire que se taire : c'est ce que
    faisait la carte du dépôt, qui listait `conversation-download` comme un dossier
    à explorer alors qu'aucun outil n'en sortait.
    """
    lines: list[str] = []
    if wired:
        lines.append(f"## Outils projet ({len(wired)}) — appelables dès maintenant")
        lines += [f"- {name}" for name in wired]
    for failure in failures:
        lines.append(f"[plugin non chargé] {failure}")
    return lines


def code_block(root: Path) -> list[str]:
    """Comment parcourir le code du projet : les outils déterministes, pointés sur lui."""
    return ["## Code", code_hint(root)]


def code_hint(root: Path) -> str:
    return (f'FindCode(query="<mots-clés ou noms>", path="{root}") pour localiser ; '
            f'Tree(path="{root}") pour l\'arborescence.')


def render(root: Path, project_name: str, header: str,
           wired: list[str], failures: list[str]) -> str:
    blocks = [header, ""]
    blocks += skills_block(root) + [""]
    plugins = plugins_block(wired, failures)
    if plugins:
        blocks += plugins + [""]
    blocks += code_block(root)
    return "\n".join(blocks)
