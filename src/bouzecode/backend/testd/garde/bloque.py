# [desc] testd : délai par test — un test qui dépasse SA limite (cf. garde.limites : adaptative, 30 s, 60 s navigateur, 300 s lent) fait tuer son sous-run, avec sa pile (faulthandler) dans le rapport [/desc]
"""Job 85b72fb9 (B4, 2026-10-14) : un test bloqué (le stub HTTP en interblocage) a tenu 295 s,
tout le délai du job (300 s), sans délai par test. faulthandler avait pourtant écrit sa pile à
120 s — il ne fait qu'écrire, il ne tue pas. pytest-timeout n'est pas installé partout et ne
s'installe pas d'office : le démon surveille lui-même le test en cours (événements du plugin).

Le `faulthandler_timeout` de la commande est ramené à la plus petite limite du sous-run (il vaut
pour tout le process), et un test n'est tué que `MARGE_S` après SA limite : la pile est alors
dans la sortie, et le rapport en cite le fil du test."""
from __future__ import annotations

import re
import time
from pathlib import Path

from ..run.split import suivi_des_tests
from .limites import Limites

MARGE_S = 5
_PERIODE_S = 2.0
_LIGNES_DE_PILE = 12
_OPTION = "faulthandler_timeout="


def faulthandler_borne(cmd: list[str], limite: int) -> list[str]:
    """La commande avec `-o faulthandler_timeout` au plus égal à la limite."""
    if limite <= 0:
        return cmd
    sortie = list(cmd)
    for rang, arg in enumerate(sortie):
        if arg.startswith(_OPTION) and rang and sortie[rang - 1] == "-o":
            actuel = float(arg[len(_OPTION):] or 0)
            sortie[rang] = _OPTION + str(min(actuel, limite) if actuel > 0 else limite)
            return sortie
    return sortie + ["-o", f"{_OPTION}{limite}"]


class GardeTest:
    """Sondée par la boucle d'attente d'un sous-run ; `bloque()` rend la note à ajouter au job
    quand un test en cours (le plus ancien d'abord) a dépassé SA limite ("" sinon) : sous xdist,
    un test lent qui tourne depuis longtemps ne masque pas un test court bloqué à côté."""

    def __init__(self, limites: Limites, navigateur: bool, cwd: str, evenements: Path,
                 sortie: Path) -> None:
        self._limites = limites
        self._navigateur = navigateur  # sous-run navigateur : tous ses tests le sont
        self._cwd = cwd
        self._evenements = evenements
        self._sortie = sortie
        self._prochain = 0.0

    def bloque(self) -> str:
        if not self._limites.vidage(self._navigateur) or time.monotonic() < self._prochain:
            return ""
        self._prochain = time.monotonic() + _PERIODE_S
        suivi = suivi_des_tests([self._evenements])
        for nodeid, ecoule in suivi["en_cours"]:
            navigateur = self._navigateur or nodeid in suivi["navigateur"]
            limite, motif = self._limites.motivee(nodeid, navigateur, nodeid in suivi["lents"],
                                                  self._cwd)
            if limite > 0 and ecoule >= limite + MARGE_S:
                return self._note(nodeid, ecoule, motif)
        return ""

    def _note(self, nodeid: str, ecoule: float, motif: str) -> str:
        pile = extrait_de_pile(self._sortie.read_text(encoding="utf-8", errors="replace"), nodeid)
        return (f"[testd] test {nodeid} bloqué depuis {ecoule:.0f} s ({motif} ; "
                f"`timeouts.per_test` / `per_test_browser` de .bouzecode/tests.yaml la fixent, "
                f"`impacted.slow` ou le marqueur `slow` la portent à 300 s) : sous-run tué, ses "
                f"tests restants n'ont pas tourné.\n"
                + (f"Pile du test (faulthandler) :\n{pile}\n" if pile else
                   "Pas de pile faulthandler dans la sortie.\n"))


def extrait_de_pile(sortie: str, nodeid: str) -> str:
    """Le fil du test dans le DERNIER vidage faulthandler (`Timeout (0:02:00)!`), appels les
    plus récents d'abord ; le premier fil à défaut."""
    debut = sortie.rfind("Timeout (")
    if debut < 0:
        return ""
    fils = re.split(r"\n\s*\n", sortie[debut:].strip())
    fichier = nodeid.split("::", 1)[0].replace("\\", "/").rsplit("/", 1)[-1]
    choisi = next((f for f in fils if fichier and fichier in f), fils[0])
    lignes = [l.strip() for l in choisi.splitlines() if l.strip() and not l.startswith("Timeout (")]
    #  Jusqu'à la ligne du test : où il attend (en haut) et d'où il l'a appelé (en bas).
    fin = next((rang for rang, l in enumerate(lignes) if fichier and fichier in l), len(lignes) - 1)
    lignes = lignes[:fin + 1]
    if len(lignes) > _LIGNES_DE_PILE:
        moitie = _LIGNES_DE_PILE // 2
        lignes = [*lignes[:moitie], "…", *lignes[-moitie:]]
    return "\n".join("    " + l for l in lignes)
