# [desc] Version d'une distribution installée, lue SANS jamais lever : métadonnées, sinon nom du dossier dist-info, sinon None — chaque repli journalisé avec sa raison. [/desc]
"""Lire la version d'un paquet installé ne doit jamais tuer un run.

Le 2026-10-12 (déploiement Focus Azure), deux runs sont morts au premier tour sur
`importlib.metadata.version("bouzecode")` → `TypeError: 'NoneType' object is not subscriptable` :
juste après un `pip install` sur le partage CIFS `/persistent`, le `bouzecode-3.5.120.dist-info`
était visible mais son METADATA illisible (cache de répertoire CIFS). Selon la version
d'importlib, le même état donne `TypeError`, ou une version `None` qui casse plus loin.

Le nom du dossier `<nom>-<version>.dist-info` porte la version : c'est le repli quand le
fichier METADATA ne se lit pas."""
from __future__ import annotations

import logging
import sys
from importlib.metadata import Distribution
from pathlib import Path

journal = logging.getLogger(__name__)


def _nom_normalise(nom: str) -> str:
    return nom.replace("-", "_").replace(".", "_").lower()


def _version_par_metadonnees(nom: str, chemins: list[str]) -> tuple[str | None, str]:
    """(version, raison de l'échec). Toute exception d'importlib est une lecture ratée."""
    distributions = list(Distribution.discover(name=nom, path=chemins))
    if not distributions:
        return None, "distribution introuvable"
    try:
        version = distributions[0].version
    except (TypeError, KeyError, OSError, ValueError) as erreur:
        return None, f"métadonnées illisibles ({type(erreur).__name__}: {erreur})"
    if not version:
        return None, "métadonnées sans champ Version (METADATA absent ou vide)"
    return version, ""


def _version_par_dossier_dist_info(nom: str, chemins: list[str]) -> str | None:
    """`bouzecode-3.5.120.dist-info` → "3.5.120", en lisant seulement les noms de dossiers."""
    nom_cherche = _nom_normalise(nom)
    for entree in chemins:
        dossier = Path(entree or ".")
        if not dossier.is_dir():
            continue
        for dist_info in sorted(dossier.glob("*.dist-info")):
            nom_dossier, _, version = dist_info.name[: -len(".dist-info")].partition("-")
            if _nom_normalise(nom_dossier) == nom_cherche and version:
                return version
    return None


def version_paquet(*noms: str, chemins: list[str] | None = None) -> str | None:
    """Version du premier nom de distribution trouvé parmi `noms`, None si aucun n'est
    installé. Ne lève jamais : un METADATA illisible retombe sur le nom du dossier
    dist-info, avec un warning qui dit pourquoi."""
    chemins = list(sys.path if chemins is None else chemins)
    for nom in noms:
        version, raison = _version_par_metadonnees(nom, chemins)
        if version:
            return version
        if raison == "distribution introuvable":
            continue
        version = _version_par_dossier_dist_info(nom, chemins)
        journal.warning("version de %s : %s ; repli sur le nom du dossier dist-info → %s",
                        nom, raison, version or "aucun dossier lisible")
        if version:
            return version
    return None
