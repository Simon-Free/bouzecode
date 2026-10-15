# [desc] Read d'un gros fichier sans plage : plan (symboles + numéros de ligne) et premières lignes au lieu du fichier entier. [/desc]
"""Plan d'un gros fichier, servi par `Read` quand aucune plage n'est demandée.

Rapport docs/reduction_tokens §2.1 et §3.2 : un `Read` complet d'un fichier inconnu (jusqu'à
50 k caractères) finissait recopié en entier dans la note, puis relu à chaque tour ; ou bien
l'agent le lisait par tranches successives, un tour par tranche. Au-delà de `SEUIL_LIGNES`,
`Read` rend donc le plan du fichier (symboles avec leurs lignes) et ses premières lignes :
l'appel suivant vise directement la bonne plage ou le bon symbole.
"""
from __future__ import annotations

import re

from .long_lines import ecourter_ligne

SEUIL_LIGNES = 300
LIGNES_DE_TETE = 120
ENTREES_MAX = 150

# Repère des fichiers sans analyseur de symboles : titres Markdown, blocs HTML nommés,
# fonctions/classes d'autres langages courants.
_REPERE = re.compile(
    r"^(#{1,3})\s+\S"                                                        # Markdown
    r"|^\s*<(script|style|section|main|header|footer|nav|form|template|table)\b"  # HTML
    r"|^\s*<\w+[^>]*\bid=\"[^\"]+\""                                           # HTML avec id
    r"|^\s*(?:export\s+)?(?:async\s+)?(?:def|class|function|fn|func)\s+\w+"    # code
    r"|^\s*\[[^\]]+\]\s*$"                                                   # sections TOML/INI
)


def _plan_symboles(file_path: str, content: str) -> list[str]:
    from ..folder_desc.symbols import extract_symbols

    lignes: list[str] = []
    for sym in extract_symbols(file_path, content):
        lignes.append(f"  {sym.kind} {sym.name}  L{sym.start_line}-{sym.end_line}")
        lignes.extend(f"    {c.kind} {sym.name}.{c.name}  L{c.start_line}-{c.end_line}"
                      for c in sym.children)
    return lignes


def _plan_reperes(content: str) -> list[str]:
    return [f"  L{i}: {ligne.strip()[:90]}"
            for i, ligne in enumerate(content.split("\n"), 1) if _REPERE.match(ligne)]


def _ecourter_garde_fin(ligne: str) -> str:
    """Tête du plan : une ligne minifiée n'y passe pas entière (seul un Read à plage la rend)."""
    corps = ligne.rstrip("\r\n")
    return ecourter_ligne(corps) + ligne[len(corps):]


def plan_du_fichier(file_path: str, content: str) -> str:
    """En-tête + plan + LIGNES_DE_TETE premières lignes numérotées."""
    lignes = content.splitlines(keepends=True)
    total = len(lignes)
    plan = _plan_symboles(file_path, content) or _plan_reperes(content)
    if len(plan) > ENTREES_MAX:
        plan = plan[:ENTREES_MAX] + [f"  … {len(plan) - ENTREES_MAX} entrées de plus"]
    tete = "".join(f"{i + 1:6}\t{_ecourter_garde_fin(l)}" for i, l in enumerate(lignes[:LIGNES_DE_TETE]))
    return (
        f"[{file_path} : {total} lignes, {len(content)} caractères — trop long pour un Read "
        f"sans plage. Voici son plan et ses {LIGNES_DE_TETE} premières lignes. Lis la partie "
        f'utile : Read(file_path, symbol="nom") ou Read(file_path, offset=<ligne-1>, limit=N) ; '
        f"le fichier entier : Read(file_path, offset=0, limit={total}).]\n"
        f"Plan :\n" + ("\n".join(plan) if plan else "  (aucun repère détecté)") + "\n\n" + tete
    )


def plan_si_sans_plage(file_path: str, content: str, limit, offset) -> str | None:
    """Le plan si `Read` n'a demandé aucune plage sur un fichier de plus de SEUIL_LIGNES."""
    if limit is not None or offset or content.count("\n") <= SEUIL_LIGNES:
        return None
    return plan_du_fichier(file_path, content)
