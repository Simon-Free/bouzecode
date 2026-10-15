# [desc] testd : préchauffage d'un worktree neuf — lecture en arrière-plan (priorité basse) des fichiers suivis et des paquets importés du venv, une fois par (dossier, HEAD), pour payer l'antivirus avant le premier run [/desc]
"""Mesuré le 2026-10-14 : Defender (temps réel) et MsSense scannent chaque fichier à sa PREMIÈRE
ouverture, 35 à 60 ms pièce. Lire 173 fichiers non Python d'un worktree neuf : 5,99 s à froid,
0,02 s ensuite ; `import demoapp.app` : 10,77 s à froid, 1,30 s ensuite. Le premier run de chaque
agent dans un worktree neuf payait tout cela.

Le démon lit donc, dès la soumission du job (en parallèle de son attente et de son exécution),
les fichiers suivis par git (`git ls-files`) puis, dans le `site-packages` du venv du job, les
paquets que ces fichiers importent directement : sources Python d'abord, sur 4 fils de priorité
basse ; le job n'attend jamais le préchauffage. Une seule passe par (racine du dépôt, HEAD) pour
la vie du démon."""
from __future__ import annotations

import logging
import re
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ..common import sans_fenetre

_journal = logging.getLogger("testd")
_TAILLE_MAX = 32 * 1024 * 1024    # au-delà : archive ou base, pas un fichier que pytest ouvre
_MORCEAU = 1024 * 1024
_LECTEURS = 4
_IMPORT = re.compile(rb"^\s*(?:from|import)\s+([A-Za-z_]\w*)", re.MULTILINE)


class Prechauffage:
    def __init__(self) -> None:
        self._faits: set[tuple[str, str]] = set()
        self._verrou = threading.Lock()
        self.passes: list[dict] = []   # une entrée par passe faite : racine, head, fichiers, octets, durée

    def demander(self, cwd: str, python: str) -> threading.Thread:
        """Lance la passe en arrière-plan ; elle ne fait rien si (racine, HEAD) est déjà chaud."""
        fil = threading.Thread(target=self._prechauffer, args=(cwd, python), name="testd-prechauffage",
                               daemon=True)
        fil.start()
        return fil

    def _prechauffer(self, cwd: str, python: str) -> None:
        _priorite_basse()
        sortie = subprocess.run(["git", "-C", cwd, "rev-parse", "--show-toplevel", "HEAD"],
                                capture_output=True, text=True, timeout=60, **sans_fenetre())
        if sortie.returncode != 0:
            return  # pas un dépôt git : rien à lister
        racine, head = sortie.stdout.split()[:2]
        with self._verrou:
            if (racine, head) in self._faits:
                return
            self._faits.add((racine, head))
        debut = time.monotonic()
        suivis = subprocess.run(["git", "-C", racine, "ls-files", "-z"], capture_output=True,
                                timeout=120, **sans_fenetre()).stdout.decode("utf-8", errors="replace")
        chemins = [Path(racine) / nom for nom in suivis.split("\0") if nom]
        #  Ce que pytest ouvre d'abord passe d'abord : sources Python, paquets qu'elles importent,
        #  puis le reste (gabarits, données, front).
        importes: set[str] = set()
        fichiers, octets = _lire_tout([c for c in chemins if c.suffix == ".py"], importes)
        fichiers_venv, octets_venv = _lire_tout(_fichiers_des_paquets(python, importes), None)
        autres = _lire_tout([c for c in chemins if c.suffix != ".py"], None)
        fichiers, octets = fichiers + autres[0], octets + autres[1]
        passe = {"racine": racine, "head": head, "fichiers": fichiers, "octets": octets,
                 "fichiers_venv": fichiers_venv, "octets_venv": octets_venv,
                 "duree_s": round(time.monotonic() - debut, 2)}
        self.passes.append(passe)
        _journal.info("préchauffage %s", passe)


def _priorite_basse() -> None:
    """Fil courant en priorité CPU basse. Pas le mode arrière-plan de Windows : il bride aussi
    les E/S, et la passe ne finissait qu'après le premier run (60 à 118 s mesurés)."""
    if sys.platform == "win32":
        import ctypes
        noyau = ctypes.windll.kernel32
        noyau.GetCurrentThread.restype = ctypes.c_void_p
        noyau.SetThreadPriority(ctypes.c_void_p(noyau.GetCurrentThread()), -1)  # BELOW_NORMAL


def _lire(chemin: Path) -> tuple[int, set]:
    """Octets lus (-1 : ignoré) et modules importés (`.py`). L'antivirus scanne à l'ouverture."""
    if not chemin.is_file() or chemin.stat().st_size > _TAILLE_MAX:
        return -1, set()
    octets = 0
    with open(chemin, "rb") as flux:
        contenu = flux.read(_MORCEAU)
        importes = ({m.decode("ascii") for m in _IMPORT.findall(contenu)} if chemin.suffix == ".py"
                    else set())
        while contenu:
            octets += len(contenu)
            contenu = flux.read(_MORCEAU)
    return octets, importes


def _lire_tout(chemins, importes: set | None) -> tuple[int, int]:
    """Lit les fichiers sur `_LECTEURS` fils : le scan de l'antivirus est une attente par
    fichier, qui se recouvre d'un fil à l'autre. Note les modules importés dans `importes`."""
    fichiers = octets = 0
    with ThreadPoolExecutor(_LECTEURS, initializer=_priorite_basse) as lecteurs:
        for lus, modules in lecteurs.map(_lire, chemins):
            if lus >= 0:
                fichiers, octets = fichiers + 1, octets + lus
            if importes is not None:
                importes.update(modules)
    return fichiers, octets


def _site_packages(python: str) -> Path | None:
    venv = Path(python).parent.parent  # sans résoudre : le python d'un venv est souvent un lien
    candidats = [venv / "Lib" / "site-packages", *venv.glob("lib/python3*/site-packages")]
    return next((c for c in candidats if c.is_dir()), None)


def _fichiers_des_paquets(python: str, importes: set[str]) -> list[Path]:
    """Fichiers des paquets importés directement, pris dans le `site-packages` du venv du job."""
    site = _site_packages(python)
    if site is None:
        return []
    chemins: list[Path] = []
    for nom in sorted(importes):
        dossier = site / nom
        if dossier.is_dir():
            chemins.extend(p for p in dossier.rglob("*") if p.suffix in (".py", ".pyc", ".pyd", ".so", ".dll"))
        chemins.extend(site.glob(f"{nom}.py"))
        chemins.extend(site.glob(f"{nom}.*.pyd"))
    return chemins
