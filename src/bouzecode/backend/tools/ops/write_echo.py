# [desc] Écho d'un Write/Edit renvoyé au modèle : aperçu numéroté (lignes réelles), zone modifiée, symboles. [/desc]
"""Ce que le modèle voit après ses propres écritures.

Le harnais retire du fil le message assistant (donc le contenu d'un Write) dès le tour
suivant : seul le résultat de l'outil survit. Il ne disait que « Created X (N lines) »,
et le rappel de l'appel coupait le contenu à 200 caractères — l'agent concluait qu'il
« ne connaissait plus » ses fichiers et les relisait (≥ 10 fois sur une session réelle).

L'écho porte donc un aperçu numéroté avec les numéros RÉELS du fichier : l'agent peut en
épingler une partie avec Snippet(file_path=…, ranges=[[a,b]]) sans relire. L'aperçu reste
sous le seuil qui déclencherait l'obligation de snippeter (snippet_wire.SNIPPET_MIN_LINES) :
c'est une possibilité, jamais une obligation nouvelle.
"""
from __future__ import annotations

import re

from .long_lines import ecourter_ligne

APERCU_COMPLET_MAX = 36   # lignes affichées en entier en dessous de ce seuil
APERCU_TETE = 22
APERCU_QUEUE = 12
SYMBOLES_MAX = 24

_SYMBOLE = re.compile(
    r"^\s*(?:async\s+def|def|class)\s+(\w+)"            # Python
    r"|^\s*(?:export\s+)?(?:async\s+)?function\s+(\w+)"  # JS function
    r"|^\s*(?:export\s+)?(?:const|let)\s+(\w+)\s*=\s*(?:async\s*)?\("  # JS fléchée
    r"|^(#{1,3})\s+(.+)$"                                # titres Markdown
)


def nombre_de_lignes(content: str) -> int:
    return content.count("\n") + (1 if content and not content.endswith("\n") else 0)


def apercu(content: str, premiere_ligne: int = 1) -> str:
    """Contenu numéroté (numéros réels) ; tête + queue au-delà de APERCU_COMPLET_MAX."""
    lignes = content.split("\n")
    if lignes and lignes[-1] == "":
        lignes = lignes[:-1]
    numeros = [f"{premiere_ligne + i:6}\t{ecourter_ligne(l)}" for i, l in enumerate(lignes)]
    if len(numeros) <= APERCU_COMPLET_MAX:
        return "\n".join(numeros)
    cache = len(numeros) - APERCU_TETE - APERCU_QUEUE
    return "\n".join(numeros[:APERCU_TETE]
                     + [f"{'':6}\t… {cache} lignes non affichées (présentes sur disque) …"]
                     + numeros[-APERCU_QUEUE:])


def symboles(content: str) -> str:
    """« nom L12, autre L40 » : de quoi viser un Snippet(symbol=…) ou une plage."""
    trouves = []
    for i, ligne in enumerate(content.split("\n"), 1):
        m = _SYMBOLE.match(ligne)
        if m:
            nom = next(g for g in (m.group(1), m.group(2), m.group(3), m.group(5)) if g)
            trouves.append(f"{nom.strip()[:40]} L{i}")
        if len(trouves) >= SYMBOLES_MAX:
            trouves.append("…")
            break
    return ", ".join(trouves)


def echo_ecriture(file_path: str, content: str) -> str:
    """Bloc ajouté au résultat d'un Write : aperçu + symboles + mode d'emploi du Snippet."""
    total = nombre_de_lignes(content)
    lignes = [f"Fichier complet sur disque : {total} lignes, {len(content)} caractères.",
              "Aperçu (numéros = lignes réelles ; garde une partie avec "
              f'Snippet(file_path="{file_path}", ranges=[[a,b]]) sans relire) :',
              apercu(content)]
    noms = symboles(content)
    if noms:
        lignes.append(f"Symboles : {noms}")
    return "\n".join(lignes)


def zone_modifiee(final_content: str, new_string: str, idx: int | None = None) -> str:
    """« Zone modifiée : lignes a–b (fichier : N lignes) » pour un Edit.

    `idx` = position du remplacement dans `final_content` (celle de old_string dans le
    contenu d'origine : le préfixe est inchangé). Sans lui, repli sur la 1re occurrence de
    new_string — qui peut exister plus haut dans le fichier et désigner de mauvaises lignes."""
    if idx is None:
        idx = final_content.find(new_string) if new_string else -1
    total = nombre_de_lignes(final_content)
    if idx < 0:
        return f"Fichier : {total} lignes."
    debut = final_content[:idx].count("\n") + 1
    fin = debut + max(new_string.count("\n") - (1 if new_string.endswith("\n") else 0), 0)
    return f"Zone modifiée : lignes {debut}–{fin} (fichier : {total} lignes)."
