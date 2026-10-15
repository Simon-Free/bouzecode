# [desc] Jeton local du serveur web_v2 : fichier ~/.bouzecode/web_v2/token, exigé en X-Bouzecode-Token sur toute mutation /api/. [/desc]
"""Le jeton qui protège les mutations du serveur web_v2 (spec ticketing B8 / S1).

Sans lui, n'importe quel onglet du navigateur pouvait lancer, tuer ou merger par un POST
`text/plain` cross-origin. Le serveur l'exige dans l'en-tête `X-Bouzecode-Token` sur tout
POST/PUT/PATCH/DELETE sous `/api/` ; les clients le lisent dans ce fichier.

Règle de vie (simple, et qui ne casse ni un redémarrage ni un second serveur) :
  * le fichier est créé au PREMIER démarrage s'il est absent ou vide ;
  * sinon il est RÉUTILISÉ tel quel — par le serveur redémarré comme par un serveur passif
    sur le même parc. Les agents déjà lancés, `bzapi.py` et les onglets ouverts gardent
    donc un jeton valide ;
  * rotation : supprimer le fichier puis redémarrer le serveur.

Le chemin est relu à chaque appel (`Path.home()`) : un HOME de test jetable a son propre jeton.
"""
from __future__ import annotations
from bouzecode.paths import data_dir as bouzecode_data_dir

import secrets
from pathlib import Path

EN_TETE = "X-Bouzecode-Token"


def chemin_du_jeton() -> Path:
    return bouzecode_data_dir() / "web_v2" / "token"


def lire_jeton() -> str:
    """Le jeton du parc courant, "" si aucun serveur ne l'a encore créé."""
    chemin = chemin_du_jeton()
    if not chemin.is_file():
        return ""
    return chemin.read_text(encoding="utf-8").strip()


def assurer_jeton() -> str:
    """Le jeton existant, ou un jeton neuf écrit en création exclusive (deux serveurs qui
    démarrent ensemble ne peuvent pas écrire deux jetons différents)."""
    existant = lire_jeton()
    if existant:
        return existant
    chemin = chemin_du_jeton()
    chemin.parent.mkdir(parents=True, exist_ok=True)
    neuf = secrets.token_urlsafe(32)
    try:
        with chemin.open("x", encoding="utf-8") as fichier:
            fichier.write(neuf)
    except FileExistsError:
        #  Un fichier VIDE (écriture interrompue) ou l'écriture concurrente d'un autre serveur.
        gagnant = lire_jeton()
        if gagnant:
            return gagnant
        chemin.write_text(neuf, encoding="utf-8")
    return neuf


def en_tetes_du_jeton() -> dict[str, str]:
    """L'en-tête à joindre à un appel au serveur local ({} si aucun jeton n'existe)."""
    jeton = lire_jeton()
    return {EN_TETE: jeton} if jeton else {}
