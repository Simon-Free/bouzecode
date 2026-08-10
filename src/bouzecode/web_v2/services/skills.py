# [desc] Éditeur de skills depuis l'UI : liste toutes les skills, lit leur .md brut, et crée/écrase/supprime des skills globales dans ~/.bouzecode/skills. [/desc]
"""Skills are just .md files (YAML front-matter + body). The builder lets you read any
skill and write GLOBAL ones to ~/.bouzecode/skills/<name>.md — which override same-named
~/.claude skills (user source has higher precedence). Saving a non-global skill forks it.
"""
from __future__ import annotations

import re
from pathlib import Path

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")

_TEMPLATE = """---
name: {name}
description: TODO — une ligne décrivant quand utiliser cette skill
---

# {name}

Instructions de la skill…
"""


def _skills_dir() -> Path:
    from bouzecode.backend.core.config import CONFIG_DIR
    return CONFIG_DIR / "skills"


def _is_editable(file_path: str) -> bool:
    try:
        Path(file_path).resolve().relative_to(_skills_dir().resolve())
        return True
    except (ValueError, OSError):
        return False


def list_skills() -> list[dict]:
    """All discoverable skills with their source; `editable` = lives in ~/.bouzecode/skills."""
    from bouzecode.backend.tools.skill.loader import load_skills
    out = []
    for s in load_skills():
        out.append({
            "name": s.name,
            "description": (s.description or "").strip().split("\n", 1)[0][:120],
            "source": getattr(s, "source", ""),
            "editable": _is_editable(s.file_path),
        })
    out.sort(key=lambda s: s["name"])
    return out


def get_skill(name: str) -> dict | None:
    """Raw .md content of a skill (for editing/cloning)."""
    from bouzecode.backend.tools.skill.loader import load_skills
    for s in load_skills():
        if s.name == name:
            try:
                content = Path(s.file_path).read_text(encoding="utf-8")
            except OSError:
                content = ""
            return {"name": name, "content": content, "source": getattr(s, "source", ""),
                    "editable": _is_editable(s.file_path)}
    return None


def new_skill_template(name: str) -> dict:
    return {"name": name, "content": _TEMPLATE.format(name=name), "source": "", "editable": True}


def frontmatter_problem(content: str) -> str:
    """Why this skill markdown would not load, or "" when it is well-formed.

    A skill whose frontmatter is not properly delimited, or whose description is
    empty, is unusable: the description is what decides when the skill loads.
    """
    from bouzecode.backend.tools.skill.frontmatter import (
        UnterminatedFrontmatterError, parse_frontmatter_fields, split_frontmatter,
    )
    try:
        split = split_frontmatter(content)
    except UnterminatedFrontmatterError as error:
        return str(error)
    if split is None:
        return ("frontmatter manquant : le fichier doit commencer par une ligne "
                "valant exactement '---'")
    fields = parse_frontmatter_fields(split[0])
    if not fields.get("name"):
        return "frontmatter incomplet : champ 'name' requis"
    if not fields.get("description"):
        return ("frontmatter incomplet : champ 'description' requis et non vide "
                "(c'est lui qui décide du chargement de la skill)")
    return ""


def save_skill(name: str, content: str) -> dict | str:
    """Write ~/.bouzecode/skills/<name>.md. Returns {name, path} or an error string."""
    name = (name or "").strip()
    if not _NAME_RE.match(name):
        return "nom invalide : minuscules, chiffres, - et _ uniquement"
    if not (content or "").strip():
        return "contenu vide"
    problem = frontmatter_problem(content)
    if problem:
        return problem
    directory = _skills_dir()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{name}.md"
    path.write_text(content, encoding="utf-8")
    return {"name": name, "path": str(path)}


def delete_skill(name: str) -> bool:
    path = _skills_dir() / f"{name}.md"
    if path.is_file():
        path.unlink()
        return True
    return False
