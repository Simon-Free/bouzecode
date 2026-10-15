# [desc] SkillResearch : recherche par mots-clés dans les skills accessibles, une ligne par résultat. [/desc]
"""Trouver une skill sans payer le catalogue entier.

`SkillList` rendait toutes les skills avec description ET `when_to_use` (~11 k car. par
appel). Ici l'agent donne des mots-clés et reçoit les N meilleures, une ligne chacune.
Mêmes skills que `Skill(name=...)` : résolution par portée de `resolve_skills()`, puis
filtre du profil (`config["_profile_skills"]`).

Score par mot-clé (insensible à la casse et aux accents) : nom 10, description /
when_to_use / déclencheurs 4, titre du corps 2, texte du corps 1. On classe d'abord par
nombre de mots-clés trouvés, puis par score.
"""
from __future__ import annotations

import re
import unicodedata

from .loader import resolve_skills

DEFAULT_LIMIT = 8
DESCRIPTION_WIDTH = 100
BODY_LINE_WIDTH = 90
_BOILERPLATE = re.compile(r"^\s*(always\s+load\s+when|use\s+(this\s+)?when|load\s+when)\s*[:,-]?\s*",
                          re.IGNORECASE)
_USE_CASES = re.compile(r"\s*\.?\s*Use cases\s*:.*$", re.IGNORECASE | re.DOTALL)

SCHEMA = {
    "name": "SkillResearch",
    "description": (
        "Cherche des skills par mots-clés (nom, description, déclencheurs, corps). "
        "Rend les meilleures, une ligne chacune ; ouvre ensuite avec Skill(name=...)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Mots-clés séparés par des espaces (ex. 'databricks deploy').",
            },
            "limit": {
                "type": "integer",
                "description": f"Nombre maximal de résultats (défaut {DEFAULT_LIMIT}).",
                "default": DEFAULT_LIMIT,
            },
        },
        "required": ["query"],
    },
}


def fold(text: str) -> str:
    """Minuscules sans accents : « Déployer » et « deployer » doivent se trouver."""
    decomposed = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in decomposed if not unicodedata.combining(c)).lower()


def short_description(skill, width: int = DESCRIPTION_WIDTH) -> str:
    """La description sans le préambule « ALWAYS LOAD WHEN … Use cases: (1) … »."""
    flat = " ".join((skill.description or skill.when_to_use or "").split()).strip("\"'")
    flat = _USE_CASES.sub("", _BOILERPLATE.sub("", flat)).strip()
    flat = flat[:1].upper() + flat[1:]
    return flat if len(flat) <= width else flat[: width - 1].rstrip() + "…"


def _body_hit(skill, keyword: str) -> tuple[int, str]:
    """(points, ligne) du meilleur passage du corps : un titre vaut plus que du texte."""
    best = (0, "")
    for number, line in enumerate((skill.prompt or "").splitlines(), start=1):
        if keyword not in fold(line):
            continue
        points = 2 if line.lstrip().startswith("#") else 1
        if points > best[0]:
            best = (points, f"L{number}: {' '.join(line.split())}")
        if points == 2:
            break
    return best


def _score(skill, keywords: list[str]) -> tuple[int, int, str]:
    """(mots-clés trouvés, score, passage du corps si c'est le corps qui a matché)."""
    name_text = fold(f"{skill.name} {skill.qualified_name}")
    meta_text = fold(" ".join([skill.description, skill.when_to_use, *skill.triggers]))
    found = score = 0
    body_line = ""
    for keyword in keywords:
        if keyword in name_text:
            points = 10
        elif keyword in meta_text:
            points = 4
        else:
            points, line = _body_hit(skill, keyword)
            body_line = body_line or line
        found += points > 0
        score += points
    return found, score, body_line


def _visible_skills(config: dict | None) -> tuple[list, object]:
    resolution = resolve_skills()
    skills = resolution.winners
    profile_skills = (config or {}).get("_profile_skills") or []
    if profile_skills:
        allowed = set(profile_skills)
        skills = [s for s in skills if s.name in allowed]
    return skills, resolution


def _result_lines(skill, body_line: str, resolution) -> list[str]:
    label = skill.qualified_name or skill.name
    lines = [f"- {label} — {short_description(skill)}"]
    if body_line:
        clipped = body_line if len(body_line) <= BODY_LINE_WIDTH else body_line[: BODY_LINE_WIDTH - 1] + "…"
        lines.append(f"    ↳ corps {clipped}")
    for loser in resolution.shadowed.get(skill.name, []):
        lines.append(f"    masque {loser.file_path}")
    return lines


def skill_research(params: dict, config: dict | None = None) -> str:
    query = (params.get("query") or "").strip()
    keywords = [k for k in fold(query).split() if k]
    if not keywords:
        return 'Erreur : query vide. Exemple : SkillResearch(query="databricks deploy").'
    limit = max(1, int(params.get("limit") or DEFAULT_LIMIT))

    skills, resolution = _visible_skills(config)
    scored = [(_score(s, keywords), s) for s in skills]
    hits = sorted(((sc, s) for sc, s in scored if sc[0]),
                  key=lambda item: (-item[0][0], -item[0][1], item[1].name))
    if not hits:
        return (f"Aucune skill ne correspond à « {query} » ({len(skills)} cherchées). "
                "Essaie d'autres mots-clés : synonymes, anglais/français, nom d'un outil, "
                "d'un module ou d'un service.")

    shown = hits[:limit]
    lines = [f"Skills pour « {query} » ({len(shown)} sur {len(hits)} correspondances) :"]
    for (_found, _points, body_line), skill in shown:
        lines += _result_lines(skill, body_line, resolution)
    lines.append('Ouvrir : Skill(name="<nom>")')
    return "\n".join(lines)
