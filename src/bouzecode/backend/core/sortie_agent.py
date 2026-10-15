# [desc] Sortie PROPRE a chaque agent du process : ce qu'un sous-agent en process ecrit sur stdout/stderr (print, avertissements de skills, de la boucle) va dans SON journal, jamais dans le terminal du principal. [/desc]
"""`sys.stdout` / `sys.stderr` sont partages par tous les fils du process. Un sous-agent du
TUI qui charge ses skills ou avertit (`print(..., file=sys.stderr)`) ecrivait donc au milieu
de la conversation du principal : des dizaines de lignes « [skill] ... masquée par ... ».

Plutot que de faire taire chaque emetteur (il y en a partout dans le backend), on route a la
source : `FluxRoutant` enveloppe un flux et, pour chaque ecriture, regarde l'atelier de
l'agent qui ecrit (`dossier_agent.actif()`, contextvar propre au fil). S'il porte une
`sortie`, le texte y va ; sinon il passe au vrai flux, a l'identique.
"""
from __future__ import annotations

import contextlib
import sys
import threading
from collections import deque
from pathlib import Path

from .dossier_agent import actif


class FluxRoutant:
    """Enveloppe d'un flux texte : l'agent qui ecrit choisit ou va son texte."""

    def __init__(self, reel) -> None:
        self._reel = reel

    def write(self, texte):
        sortie = getattr(actif(), "sortie", None)
        if sortie is None:
            return self._reel.write(texte)
        sortie.write(texte)
        return len(texte)

    def flush(self):
        sortie = getattr(actif(), "sortie", None)
        return sortie.flush() if sortie is not None else self._reel.flush()

    def __getattr__(self, nom):
        # `isatty`, `encoding`, `fileno`... : tout le reste appartient au vrai flux.
        return getattr(self._reel, nom)


_installe = False


def installer() -> None:
    """Enveloppe stdout et stderr (idempotent : jamais deux couches)."""
    global _installe
    _installe = True
    if not isinstance(sys.stdout, FluxRoutant):
        sys.stdout = FluxRoutant(sys.stdout)
    if not isinstance(sys.stderr, FluxRoutant):
        sys.stderr = FluxRoutant(sys.stderr)


def reposer() -> None:
    """Remet le routage au sommet apres qu'un tiers a pose son flux (le `rich.Live` du texte
    de main remplace sys.stdout par son FileProxy, et le restaure sans condition a l'arret).
    Sans effet tant que `installer()` n'a jamais ete appele (hors TUI : rien ne change)."""
    if _installe:
        installer()


@contextlib.contextmanager
def routage():
    """`installer()` le temps d'un bloc, par-dessus un flux pose par un tiers (le
    `patch_stdout` de prompt_toolkit remplace sys.stdout pendant la saisie et ecrit au-dessus
    de l'invite) ; rend ensuite exactement les flux trouves en entrant."""
    avant = sys.stdout, sys.stderr
    installer()
    try:
        yield
    finally:
        sys.stdout, sys.stderr = avant


class JournalAgent:
    """Sortie d'un sous-agent : un fichier a lui (ajout), plus les dernieres lignes en
    memoire pour sa vue. Sur fichier des la premiere ecriture, ouvert/ferme a chaque fois :
    rien ne reste tenu (Windows refuse de supprimer un fichier ouvert)."""

    def __init__(self, chemin: Path, garder: int = 200) -> None:
        self.chemin = Path(chemin)
        self.dernieres = deque(maxlen=garder)
        self._verrou = threading.Lock()
        self._ligne = ""

    def write(self, texte: str) -> int:
        with self._verrou:
            self.chemin.parent.mkdir(parents=True, exist_ok=True)
            with open(self.chemin, "a", encoding="utf-8", errors="replace") as fichier:
                fichier.write(texte)
            morceaux = (self._ligne + texte).split("\n")
            self._ligne = morceaux.pop()
            self.dernieres.extend(m for m in morceaux if m.strip())
        return len(texte)

    def flush(self) -> None:
        return None
