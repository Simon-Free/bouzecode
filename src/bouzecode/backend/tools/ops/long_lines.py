# [desc] Lignes géantes (HTML/JS minifiés) dans les échos d'outils : ligne écourtée, fenêtre du changement, plafond en caractères. [/desc]
"""Borner la LONGUEUR des lignes renvoyées au modèle, pas seulement leur nombre.

Mesuré : un Edit raccourcissant un <p> de docs/cartographie_code/evaluation.html (lignes de
4 k à 18 k caractères, une <table> par ligne) a renvoyé 32 379 caractères — le diff à
3 lignes de contexte était plafonné en LIGNES, jamais en longueur. Ici :

- une ligne de plus de `SEUIL_LIGNE` caractères devient tête + « … N car. … » + fin ;
- une ligne retirée appariée à une ligne ajoutée ne montre que la fenêtre qui change
  (préfixe et suffixe communs ôtés, `CONTEXTE_FENETRE` caractères autour), avec la position
  en caractères : le modèle voit exactement ce qu'il a changé ;
- une ligne de `SEUIL_LIGNE` caractères ou moins est rendue telle quelle : un fichier
  ordinaire produit la même sortie qu'avant.
"""
from __future__ import annotations

SEUIL_LIGNE = 200
CONTEXTE_FENETRE = 100
CHANGEMENT_MAX = 400   # au-delà, le segment changé lui-même est écourté
PLAFOND_DIFF_CAR = 8000
OMISSION_MIN = 40      # en dessous, écourter ne gagne rien


def ecourter_ligne(ligne: str, seuil: int = SEUIL_LIGNE) -> str:
    """Tête + « … N car. … » + fin si la ligne dépasse `seuil` ; sinon inchangée.

    Une ligne qui ne dépasse que de quelques caractères reste entière : le marqueur
    coûterait autant que ce qu'il cache."""
    longueur_tete = seuil * 2 // 3
    longueur_fin = seuil - longueur_tete
    omis = len(ligne) - longueur_tete - longueur_fin
    if omis <= OMISSION_MIN:
        return ligne
    return f"{ligne[:longueur_tete]} … {omis} car. … {ligne[-longueur_fin:]}"


def _bornes_communes(ancienne: str, nouvelle: str) -> tuple[int, int]:
    """(préfixe commun, suffixe commun) sans chevauchement."""
    prefixe = 0
    borne = min(len(ancienne), len(nouvelle))
    while prefixe < borne and ancienne[prefixe] == nouvelle[prefixe]:
        prefixe += 1
    suffixe = 0
    while (suffixe < borne - prefixe
           and ancienne[-1 - suffixe] == nouvelle[-1 - suffixe]):
        suffixe += 1
    return prefixe, suffixe


def _fenetre(ligne: str, prefixe: int, suffixe: int) -> str:
    debut = max(0, prefixe - CONTEXTE_FENETRE)
    fin = min(len(ligne), len(ligne) - suffixe + CONTEXTE_FENETRE)
    avant = ligne[debut:prefixe]
    change = ecourter_ligne(ligne[prefixe:len(ligne) - suffixe], CHANGEMENT_MAX)
    apres = ligne[len(ligne) - suffixe:fin]
    ouverture = "…" if debut > 0 else ""
    fermeture = "…" if fin < len(ligne) else ""
    return (f"[car. {debut + 1}–{fin} sur {len(ligne)}] "
            f"{ouverture}{avant}{change}{apres}{fermeture}")


def fenetres_du_changement(ancienne: str, nouvelle: str) -> tuple[str, str]:
    """Ligne retirée / ligne ajoutée réduites à la zone qui diffère, si l'une est longue."""
    if len(ancienne) <= SEUIL_LIGNE and len(nouvelle) <= SEUIL_LIGNE:
        return ancienne, nouvelle
    fin_ancienne = "\r" if ancienne.endswith("\r") else ""   # positions = caractères du texte, CR exclu
    fin_nouvelle = "\r" if nouvelle.endswith("\r") else ""
    ancienne, nouvelle = ancienne[:len(ancienne) - len(fin_ancienne)], nouvelle[:len(nouvelle) - len(fin_nouvelle)]
    prefixe, suffixe = _bornes_communes(ancienne, nouvelle)
    return (_fenetre(ancienne, prefixe, suffixe) + fin_ancienne,
            _fenetre(nouvelle, prefixe, suffixe) + fin_nouvelle)


def _compacter_bloc(retirees: list[str], ajoutees: list[str]) -> list[str]:
    """Un bloc « - » suivi d'un bloc « + » : la i-ème retirée est appariée à la i-ème ajoutée."""
    sorties_retirees, sorties_ajoutees = [], []
    for rang in range(max(len(retirees), len(ajoutees))):
        if rang < len(retirees) and rang < len(ajoutees):
            ancienne, nouvelle = fenetres_du_changement(retirees[rang][1:], ajoutees[rang][1:])
            sorties_retirees.append("-" + ancienne)
            sorties_ajoutees.append("+" + nouvelle)
        elif rang < len(retirees):
            sorties_retirees.append(ecourter_ligne(retirees[rang]))
        else:
            sorties_ajoutees.append(ecourter_ligne(ajoutees[rang]))
    return sorties_retirees + sorties_ajoutees


def compacter_diff(diff_text: str) -> str:
    """Diff unifié aux lignes longues écourtées ; lignes courtes rendues à l'identique.

    Les en-têtes (`---`/`+++` avant le premier `@@`) et les lignes `@@` passent telles quelles :
    dans un hunk, une ligne retirée commençant par « -- » reste une ligne retirée."""
    lignes = diff_text.split("\n")
    sortie: list[str] = []
    rang = 0
    while rang < len(lignes) and not lignes[rang].startswith("@@"):
        sortie.append(lignes[rang])
        rang += 1
    while rang < len(lignes):
        ligne = lignes[rang]
        if ligne.startswith("-"):
            retirees, ajoutees = [], []
            while rang < len(lignes) and lignes[rang].startswith("-"):
                retirees.append(lignes[rang])
                rang += 1
            while rang < len(lignes) and lignes[rang].startswith("+"):
                ajoutees.append(lignes[rang])
                rang += 1
            sortie.extend(_compacter_bloc(retirees, ajoutees))
            continue
        sortie.append(ligne if ligne.startswith("@@") else ecourter_ligne(ligne))
        rang += 1
    return "\n".join(sortie)


def plafonner_caracteres(texte: str, plafond: int = PLAFOND_DIFF_CAR) -> str:
    """Coupe à la dernière fin de ligne sous `plafond`, avec le nombre de lignes omises."""
    if len(texte) <= plafond:
        return texte
    coupe = texte.rfind("\n", 0, plafond)
    coupe = coupe if coupe > 0 else plafond
    omises = texte[coupe:].count("\n")
    return texte[:coupe] + f"\n\n[... {omises} more lines, {len(texte) - coupe} more chars ...]"
