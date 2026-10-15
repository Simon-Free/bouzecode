# [desc] Régénère la table des routes de la skill `bouzecode/web-api` depuis le schéma d'API : la section entre les marqueurs est réécrite, le reste (texte écrit à la main) est gardé. [/desc]
"""La skill n'a plus de table d'endpoints écrite à la main (constat P7 : elle mentait sur la forme
des réponses). `scripts/regenerer_skill_web_api.py` réécrit la section générée ; le test
`tests/test_skill_web_api_a_jour.py` échoue si le fichier versionné n'est plus à jour."""
from __future__ import annotations

from pathlib import Path

DEBUT = "<!-- DEBUT DE LA SECTION GENEREE (scripts/regenerer_skill_web_api.py) : ne pas editer -->"
FIN = "<!-- FIN DE LA SECTION GENEREE -->"

#  Le périmètre de la skill : consommer les tickets, les agents et leurs conversations. Le reste
#  (Bureau, agent-builder, enquête…) est dans GET /api/schema.
PREFIXES = ("/api/projects", "/api/agents", "/api/sessions", "/api/schema")
CHEMIN_SKILL = Path(".bouzecode") / "skills" / "bouzecode" / "web-api.md"


def _cellule(texte: str) -> str:
    return texte.replace("|", "\\|").replace("\n", " ").strip()


def _dans_le_perimetre(cle: str) -> bool:
    chemin = cle.split(" ", 1)[1]
    return any(chemin == p or chemin.startswith(p + "/") or chemin.startswith(p + "?")
               for p in PREFIXES)


def section(schema: dict) -> str:
    """La section générée : une ligne par route du périmètre, son corps déclaré s'il y en a un."""
    corps = schema.get("corps") or {}
    lignes = [DEBUT, "",
              f"Routes de {', '.join(f'`{p}`' for p in PREFIXES)} — générées depuis "
              "`GET /api/schema` (docstrings des vues + corps déclarés par `@corps_attendu`).",
              "", "| Route | Ce qu'elle fait | Corps |", "|---|---|---|"]
    for cle, description in schema["endpoints"].items():
        if not _dans_le_perimetre(cle):
            continue
        declare = corps.get(cle) or {}
        champs = " · ".join(f"`{nom}` : {_cellule(c)}" for nom, c in declare.items())
        lignes.append(f"| `{cle}` | {_cellule(description)} | {champs} |")
    lignes += ["", FIN]
    return "\n".join(lignes)


def regenerer(texte: str, schema: dict) -> str:
    """Le texte de la skill avec sa section générée remplacée (les fins de ligne sont gardées)."""
    fin_de_ligne = "\r\n" if "\r\n" in texte else "\n"
    texte = texte.replace("\r\n", "\n")
    debut, fin = texte.index(DEBUT), texte.index(FIN) + len(FIN)
    nouveau = texte[:debut] + section(schema) + texte[fin:]
    return nouveau.replace("\n", fin_de_ligne)
