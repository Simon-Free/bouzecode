# [desc] Normalizes delivered-file lists into deduplicated absolute-path entries and adds existence info for bouzeui. [/desc]
"""« Fichiers livrés » d'une livraison : les livrables que l'humain consulte au lieu de relire
le code (rapport .html, .pptx, .pbix, export .xlsx/.pdf…).

Format unique, agent comme humain : liste d'objets ``{"path": <absolu>, "label"?: str,
"kind"?: str}``. Fonction PURE et tolérante : un texte JSON (protocole XML), une chaîne seule
(un chemin) ou un objet sans `path` absolu sont acceptés ou ignorés, jamais une exception."""
from __future__ import annotations

import json
import os

MAX_FICHIERS = 50


def _est_absolu(chemin: str) -> bool:
    return os.path.isabs(chemin) or (len(chemin) > 2 and chemin[1] == ":" and chemin[2] in "\\/")


def normaliser_related_files(valeur: object) -> list[dict]:
    """Liste propre ``[{path, label, kind}]`` (doublons de chemin retirés, chemins relatifs
    ignorés : bouzeui ne saurait pas les ouvrir)."""
    if isinstance(valeur, str):
        texte = valeur.strip()
        if not texte:
            return []
        try:
            valeur = json.loads(texte)
        except ValueError:
            valeur = [texte]
    if isinstance(valeur, dict):
        valeur = [valeur]
    if not isinstance(valeur, list):
        return []
    sortie: list[dict] = []
    vus: set[str] = set()
    for item in valeur:
        if isinstance(item, str):
            item = {"path": item}
        if not isinstance(item, dict):
            continue
        chemin = str(item.get("path") or "").strip().strip('"')
        if not chemin or not _est_absolu(chemin):
            continue
        cle = os.path.normcase(os.path.normpath(chemin))
        if cle in vus:
            continue
        vus.add(cle)
        sortie.append({"path": chemin,
                       "label": str(item.get("label") or "").strip(),
                       "kind": str(item.get("kind") or "").strip()})
        if len(sortie) >= MAX_FICHIERS:
            break
    return sortie


def meme_chemin(a: str, b: str) -> bool:
    """Deux chemins désignent-ils le même fichier (casse et séparateurs normalisés) ?"""
    return os.path.normcase(os.path.normpath(a)) == os.path.normcase(os.path.normpath(b))


def avec_existence(fichiers: list[dict]) -> list[dict]:
    """Ajoute `name` et `exists` à chaque fichier (affichage bouzeui)."""
    return [{**f, "name": os.path.basename(f["path"].rstrip("\\/")) or f["path"],
             "exists": os.path.isfile(f["path"])} for f in fichiers]
