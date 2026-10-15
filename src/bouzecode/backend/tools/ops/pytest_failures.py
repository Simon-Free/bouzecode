# [desc] Extrait utile d'un échec pytest : ligne du test, lignes `E `, pile réduite aux emplacements, sorties capturées bornées. [/desc]
"""Quand des tests échouent, le résultat renvoyé au modèle doit montrer POURQUOI.

La troncature générique garde tête + queue de la sortie : sur une section FAILURES de 900
lignes (deux tracebacks qui traversent toute la boucle d'agent), elle gardait le code source
du premier test et la fin du second, et coupait au milieu la ligne `E   AssertionError` du
premier. L'agent relisait alors le fichier complet quatre fois par Bash pour la retrouver
(autopsie 9f14d1810dd5, 2026-10-05). Ici, l'ordre de priorité est fixé : ligne de verdict,
liste `FAILED …`, puis pour chaque échec la ligne du test, les lignes `E `, la pile réduite
aux emplacements et les sections capturées — dans le budget fixé par `pytest_compact`.
"""
from __future__ import annotations

import re


_TITRE_ECHEC_RE = re.compile(r"^_+ ([^_ ].*?) _+$")  # `_ _ _` sépare les frames, pas les tests
_TITRE_CAPTURE_RE = re.compile(r"^-{3,} (.+?) -{3,}$")
MAX_CAPTURES = 700  # sorties capturées d'un échec : début et fin, le reste dans le fichier
_EMPLACEMENT_RE = re.compile(r"^\S.*:\d+:(?: |$)")  # `x.py:53: ` ou `x.py:53: AssertionError`


def _couper(texte: str, limite: int) -> str:
    if len(texte) <= limite:
        return texte
    return texte[:max(limite - 40, 0)] + f"… [+{len(texte) - limite} car.]"


def _couper_milieu(texte: str, limite: int) -> str:
    """Garde les premières et les dernières LIGNES qui tiennent dans `limite`, coupe le milieu."""
    if len(texte) <= limite:
        return texte
    lignes = texte.split("\n")
    tete, queue, place = [], [], max(limite - 40, 0)
    while lignes:
        cote_tete = len(tete) <= len(queue)
        ligne = lignes.pop(0) if cote_tete else lignes.pop()
        if len(ligne) + 1 > place:
            break
        (tete if cote_tete else queue).append(ligne)
        place -= len(ligne) + 1
    coupe = len(texte) - sum(len(l) + 1 for l in tete + queue)
    if not tete:
        return _couper(texte, limite)
    return "\n".join([*tete, f"… [{coupe} car. coupés]", *reversed(queue)])


def blocs_d_echec(lignes: list[str]) -> list[tuple[str, list[str]]]:
    blocs: list[tuple[str, list[str]]] = []
    for ligne in lignes:
        if m := _TITRE_ECHEC_RE.match(ligne.strip()):
            blocs.append((m.group(1), []))
        elif blocs:
            blocs[-1][1].append(ligne)
    return blocs


def extrait_d_echec(nom: str, lignes: list[str], budget: int) -> str:
    """La ligne du test, les lignes `E `, la pile façon --tb=short, puis les captures."""
    trace: list[str] = []
    captures: list[tuple[str, list[str]]] = []
    for ligne in lignes:
        if m := _TITRE_CAPTURE_RE.match(ligne.strip()):
            captures.append((m.group(1), []))
        elif captures:
            captures[-1][1].append(ligne)
        else:
            trace.append(ligne)
    pointees = [l for l in trace if l.startswith(">")]
    erreurs = [l for l in trace if l.startswith("E ") or l == "E"]
    # Pile façon --tb=short : la ligne pointée de chaque frame et son emplacement.
    pile = [l.rstrip() for l in trace[trace.index(pointees[0]) + 1 if pointees else 0:]
            if l.startswith(">") or (_EMPLACEMENT_RE.match(l) and not l.startswith("E "))]
    if not erreurs:  # erreur de collecte, crash : la fin de la trace porte le message
        erreurs = [l for l in trace if l.strip()][-15:]
    morceaux = [f"____ {nom} ____"]
    if pointees:
        morceaux.append(_couper(pointees[0].rstrip(), 300))
    morceaux.append(_couper("\n".join(erreurs), budget * 55 // 100))
    if pile:  # la moitié de ce qui reste (tout s'il n'y a rien de capturé)
        place = budget - sum(len(m) + 1 for m in morceaux)
        place = place // 2 if captures else place
        morceaux.append("pile :\n" + _couper_milieu("\n".join(pile), max(place, 200)))
    reste = min(budget - sum(len(m) + 1 for m in morceaux), MAX_CAPTURES)
    for titre, contenu in captures:
        if reste < 200:
            morceaux.append(f"--- {titre} : voir le fichier complet ---")
            break
        corps = _couper_milieu("\n".join(contenu).strip(), reste - len(titre) - 10)
        morceaux.append(f"--- {titre} ---\n{corps}")
        reste -= len(morceaux[-1]) + 1
    return "\n".join(morceaux)
