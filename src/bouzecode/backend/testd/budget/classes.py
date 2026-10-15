# [desc] testd : classement navigateur / hors navigateur de chaque fichier de test (clé = chemin + mtime), à côté des durées ; décide si un job peut sauter la collecte [/desc]
"""Mesuré le 2026-10-14 : la collecte qui sépare les tests navigateur coûte 5 à 8 s sur
demoapp_clone, soit tout le gain du navigateur chaud sur un petit job. Le classement d'un fichier
est mémorisé (`~/.bouzecode/test_durations/fichiers/<dépôt>.json`) tant que son mtime ne bouge
pas ; un job dont toutes les cibles sont des fichiers déjà classés saute la collecte.

`v` : version des règles de classement du plugin. Quand elles changent (2 : un module qui importe
un lanceur de navigateur maison, cf. `_bz_testd_plugin`), les classements anciens sont ignorés —
sinon les fichiers d'exercices de demoapp_clone, classés « hors navigateur » à tort le 2026-10-14,
le resteraient jusqu'à leur prochaine modification."""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path

from .durations import PETITE_DUREE_S, estimer

_verrou = threading.Lock()
VERSION_CLASSEMENT = 2


def fichier_classes(historique: Path) -> Path:
    """Sous-dossier : le dossier des durées ne garde qu'un `<dépôt>.json` par dépôt."""
    dossier = historique.parent / "fichiers"
    dossier.mkdir(parents=True, exist_ok=True)
    return dossier / historique.name


def _charger(fichier: Path) -> dict:
    return json.loads(fichier.read_text(encoding="utf-8")) if fichier.exists() else {}


def _mtime(cwd: str, chemin: str) -> float | None:
    fichier = Path(cwd) / chemin
    return fichier.stat().st_mtime if fichier.is_file() else None


def _cle(cwd: str, cible: str) -> str:
    """Chemin posix relatif à `cwd` (comme un nodeid), quelle que soit l'écriture de la cible."""
    chemin = Path(cible.split("::", 1)[0])
    if chemin.is_absolute():
        chemin = chemin.relative_to(Path(cwd))
    return chemin.as_posix()


def memoriser(historique: Path, cwd: str, groupes: dict, filtre: bool) -> None:
    """Classe les fichiers vus à la collecte. Un fichier vu avec un test navigateur est
    navigateur ; « hors navigateur » n'est retenu que si la collecte n'était pas filtrée (`-k`,
    `-m`, ids), sinon un test navigateur écarté passerait inaperçu."""
    vus: dict[str, bool] = {}
    for groupe, navigateur in (("other", False), ("browser", True)):
        for nodeid in groupes.get(groupe) or []:
            fichier = nodeid.split("::", 1)[0]
            vus[fichier] = vus.get(fichier, False) or navigateur
    nouveaux = {f: {"mtime": m, "browser": b, "v": VERSION_CLASSEMENT} for f, b in vus.items()
                if (b or not filtre) and (m := _mtime(cwd, f)) is not None}
    if not nouveaux:
        return
    with _verrou:
        fichier = fichier_classes(historique)
        contenu = {**_charger(fichier), **nouveaux}
        provisoire = fichier.with_suffix(f".{os.getpid()}.tmp")
        provisoire.write_text(json.dumps(contenu, sort_keys=True), encoding="utf-8")
        os.replace(provisoire, fichier)


def plan_sans_collecte(historique: Path, cwd: str, cibles: list[str], durees: dict) -> dict | None:
    """Sauter la collecte ? None : il faut collecter. Sinon {"browser": bool, "nodeids": [...]}.

    Toutes les cibles doivent être des FICHIERS déjà classés (mtime inchangé). Sans navigateur :
    lancé directement. Avec navigateur : seulement si l'estimation est sous ~10 s (sinon la
    séparation et le `-n` paient la collecte)."""
    if not cibles:
        return None
    classes = _charger(fichier_classes(historique))
    fichiers = []
    for cible in cibles:
        if Path(cible).is_absolute() and not Path(cible).is_relative_to(Path(cwd)):
            return None
        cle = _cle(cwd, cible)
        connu = classes.get(cle)
        if (not cle.endswith(".py") or connu is None or connu.get("v") != VERSION_CLASSEMENT
                or connu["mtime"] != _mtime(cwd, cle)):
            return None
        fichiers.append((cle, connu["browser"]))
    noms = {f for f, _ in fichiers}
    nodeids = [n for n in durees if n.split("::", 1)[0] in noms]
    navigateur = any(b for _, b in fichiers)
    if navigateur and estimer(nodeids, durees, navigateur=True) >= PETITE_DUREE_S:
        return None
    return {"browser": navigateur, "nodeids": nodeids}
