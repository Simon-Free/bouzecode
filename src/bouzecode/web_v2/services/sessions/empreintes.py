# [desc] Empreintes de sessions persistées par version de fichier : ce que le Bureau lit d'une session (clôture, récap), calculé UNE fois par version, jamais au démarrage d'un process. [/desc]
"""Ce que l'écran lit d'une session FINIE ne change plus : sa clôture (`close_reason`,
`final_answer`) et le récap de sa réponse finale. Pour l'obtenir il faut pourtant décoder le
JSON ENTIER (jusqu'à 112 Mo) : les deux champs sont écrits après le tableau `messages`.

Les mémoires d'avant (`liveness._clotures`, `taches_vue._recap_memo`) ne vivaient que dans le
PROCESS : chaque redémarrage du serveur redécodait toutes les sessions du parc sur le chemin
de la première requête. Mesuré le 2026-09-29 sur le poste, process neuf : 712 sessions
décodées par le premier `GET /api/inbox`, 5,6 s cache disque chaud et **63 s** cache froid
(l'ouverture des gros fichiers domine).

Ici la même empreinte est calculée quand le FICHIER change (nouvelle version = nouveau
mtime), puis retenue sur disque à côté de l'index de méta. Un process neuf relit ce petit
fichier une fois et ne décode plus aucune session déjà vue. Même principe que
`meta_index`/`status_cache` : lecture mémoire, écriture groupée et fusionnée
(`meta_index.merge_into_file`), deux serveurs concurrents ne se volent pas leurs entrées.

Les écritures sont GROUPÉES : `retenir` n'écrit rien, `ecrire_tout()` est appelé en fin de
calcul d'écran (arbre, lignes, boîte) — une écriture pour tout un écran, pas une par session.
"""
from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Callable

from . import meta_index

_toutes: list["Empreintes"] = []


class Empreintes:
    """Une empreinte par fichier de session, valide pour UN mtime et UNE version du calcul.

    `nom_fichier` vit à côté de `store.CACHE_PATH`, relu à chaque appel (les tests le
    redirigent vers leur tmp, et l'empreinte suit sans second chemin à connaître). Changer
    `version` invalide toutes les entrées d'un calcul dont la forme a changé."""

    def __init__(self, nom_fichier: str, version: int):
        self.nom_fichier = nom_fichier
        self.version = version
        self._lock = threading.Lock()
        self._chemin_charge: Path | None = None
        self._entrees: dict[str, dict] = {}
        self._a_ecrire: dict[str, dict] = {}
        _toutes.append(self)

    def chemin(self) -> Path:
        from . import store
        return store.CACHE_PATH.with_name(self.nom_fichier)

    def _charger(self) -> dict[str, dict]:
        """Entrées en mémoire, lues sur disque une fois par process (et par chemin)."""
        chemin = self.chemin()
        if self._chemin_charge != chemin:
            self._entrees = meta_index.read_file(chemin)
            self._a_ecrire = {}
            self._chemin_charge = chemin
        return self._entrees

    def lire(self, session: Path, calcul: Callable[[], dict | None]) -> dict | None:
        """Empreinte de `session` pour sa version courante ; `calcul()` seulement si elle est
        inconnue. None si le fichier est absent ou si `calcul` rend None (session en cours
        d'écriture, illisible) : rien n'est alors retenu, le prochain appel réessaie."""
        try:
            mtime = os.stat(session).st_mtime
        except OSError:
            return None
        cle = str(session)
        with self._lock:
            entree = self._charger().get(cle)
        if isinstance(entree, dict) and entree.get("mtime") == mtime \
                and entree.get("v") == self.version:
            return entree.get("valeur")
        valeur = calcul()
        if valeur is None:
            return None
        with self._lock:
            nouvelle = {"mtime": mtime, "v": self.version, "valeur": valeur}
            self._charger()[cle] = nouvelle
            self._a_ecrire[cle] = nouvelle
        return valeur

    def ecrire(self) -> None:
        """Écrit les empreintes calculées depuis le dernier appel (no-op si aucune)."""
        with self._lock:
            fraiches, self._a_ecrire = self._a_ecrire, {}
            chemin = self._chemin_charge
        if fraiches and chemin is not None:
            meta_index.merge_into_file(chemin, fraiches)

    def oublier(self) -> None:
        """Oublie la mémoire (le fichier reste) : simule un process neuf."""
        with self._lock:
            self._chemin_charge = None
            self._entrees = {}
            self._a_ecrire = {}


def ecrire_tout() -> None:
    """Écrit les empreintes en attente de toutes les familles (fin d'un calcul d'écran)."""
    for empreintes in _toutes:
        empreintes.ecrire()


def oublier_tout() -> None:
    """Oublie la mémoire de toutes les familles (isolation des tests)."""
    for empreintes in _toutes:
        empreintes.oublier()
