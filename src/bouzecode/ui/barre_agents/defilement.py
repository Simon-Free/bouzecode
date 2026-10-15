# [desc] Defilement horizontal (marquee) d'une ligne de la barre des agents trop large : decalage fonction du temps, pause en fin, retour a 0, pause, et ainsi de suite. Logique pure. [/desc]
"""Une ligne plus large que l'ecran defile vers la gauche jusqu'a montrer sa fin, s'y arrete
`PAUSE_FIN` s, revient d'un coup au debut, s'y arrete `PAUSE_DEBUT` s, et recommence.

Le decalage ne depend QUE de l'heure passee (`maintenant`) : aucun etat a tenir, et chaque
redessin (invite prompt_toolkit, spinner, rich.Live) tombe sur la bonne position.
"""
from __future__ import annotations

VITESSE = 8.0      # caracteres par seconde
PAUSE_DEBUT = 2.0  # secondes immobile au decalage 0 (le debut se lit)
PAUSE_FIN = 1.5    # secondes immobile en fin de course (la conso se lit)


def decalage(longueur: int, largeur: int, maintenant: float) -> int:
    """Premier caractere visible d'un texte de `longueur` dans `largeur` colonnes."""
    debord = longueur - largeur
    if debord <= 0:
        return 0
    course = debord / VITESSE
    instant = maintenant % (PAUSE_DEBUT + course + PAUSE_FIN)
    if instant < PAUSE_DEBUT:
        return 0
    return min(debord, int((instant - PAUSE_DEBUT) * VITESSE))


def fenetre(texte: str, largeur: int, maintenant: float) -> str:
    """La portion visible de `texte` a l'instant `maintenant` (le texte entier s'il tient)."""
    largeur = max(0, largeur)
    debut = decalage(len(texte), largeur, maintenant)
    return texte[debut:debut + largeur]
