# [desc] testd : durées mesurées des tests par dépôt (`~/.bouzecode/test_durations/<dépôt>.json`), estimation d'un job et choix de son `-n` [/desc]
"""Les durées viennent des événements du plugin (somme setup + call + teardown de chaque test),
pas d'un `--durations=0` à reparser. Clé = nodeid (relatif au rootdir), donc partagée par les
worktrees d'un même dépôt.

Choix du `-n` : chaque worker réimporte l'appli (des secondes sur demo). Sous ~20 tests ou
~10 s estimées, pas de xdist ; sinon min(4, accordé, max(fichiers, tests lourds)).

Job 29367671 (B4, 2026-10-14) : 8 tests d'UN fichier, dont deux de 37 et 9 s, joués en série en
162 s : le `-n` était borné par le nombre de FICHIERS (1). xdist répartit test par test : chaque
test lourd (≥ 2 s) peut prendre un worker. Un test navigateur jamais mesuré compte 10 s (un
navigateur + un serveur par test), pas 0,5 s."""
from __future__ import annotations

import json
import os
import subprocess
import threading
from pathlib import Path

from ..common import dossier_testd, sans_fenetre

PETITE_DUREE_S = 10.0
DUREE_INCONNUE_S = PETITE_DUREE_S / 20  # 20 tests inconnus = la limite
DUREE_INCONNUE_NAVIGATEUR_S = PETITE_DUREE_S  # un seul test navigateur inconnu suffit
TEST_LOURD_S = 2.0
_verrou = threading.Lock()


def nom_du_depot(cwd: str) -> str:
    """Nom du dépôt PRINCIPAL (un worktree partage les durées de son dépôt)."""
    sortie = subprocess.run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
                            cwd=cwd, capture_output=True, text=True, timeout=30,
                            **sans_fenetre())
    if sortie.returncode == 0 and sortie.stdout.strip():
        return Path(sortie.stdout.strip()).parent.name
    return Path(cwd).resolve().name


def fichier_durees(cwd: str) -> Path:
    dossier = dossier_testd().parent / "test_durations"
    dossier.mkdir(parents=True, exist_ok=True)
    return dossier / f"{nom_du_depot(cwd)}.json"


def charger(fichier: Path) -> dict:
    return json.loads(fichier.read_text(encoding="utf-8")) if fichier.exists() else {}


def fusionner(fichier: Path, mesures: dict) -> None:
    """Ajoute les durées d'un run (écriture atomique : d'autres jobs lisent le fichier)."""
    if not mesures:
        return
    with _verrou:
        durees = charger(fichier)
        durees.update({nodeid: round(d, 3) for nodeid, d in mesures.items()})
        provisoire = fichier.with_suffix(f".{os.getpid()}.tmp")
        provisoire.write_text(json.dumps(durees, sort_keys=True), encoding="utf-8")
        os.replace(provisoire, fichier)


def _duree(nodeid: str, durees: dict, navigateur: bool) -> float:
    return durees.get(nodeid, DUREE_INCONNUE_NAVIGATEUR_S if navigateur else DUREE_INCONNUE_S)


def estimer(nodeids: list[str], durees: dict, navigateur: bool = False) -> float:
    return sum(_duree(n, durees, navigateur) for n in nodeids)


def workers_voulus(nodeids: list[str], durees: dict, plafond: int, navigateur: bool = False) -> int:
    """`-n` souhaité pour ces tests (0 = sans xdist, jamais 1 : un seul worker ne fait que coûter
    un process). Un test jamais mesuré compte 0,5 s (10 s s'il est navigateur) : sans historique,
    « petit » revient à moins de 20 tests ; avec, à moins de 10 s estimées."""
    if plafond <= 1 or estimer(nodeids, durees, navigateur) < PETITE_DUREE_S:
        return 0
    fichiers = {n.split("::", 1)[0] for n in nodeids}
    lourds = sum(1 for n in nodeids if _duree(n, durees, navigateur) >= TEST_LOURD_S)
    voulu = min(plafond, max(len(fichiers), lourds))
    return voulu if voulu > 1 else 0
