# [desc] Défense en profondeur : sous pytest, les écrivains du store refusent tout chemin du VRAI ~/.bouzecode (erreur bruyante). [/desc]
"""Deux fuites du 2026-10-06 : des tests ont écrit dans le vrai `~/.bouzecode` (fiches
`remote/executions`, puis `web_v2/projects.json` écrasé) parce que pytest tournait sans
`pytest_home_etanche`. Le HOME est désormais redirigé dès `import bouzecode` sous pytest ; ce
garde est le second verrou : un écrivain du store qui viserait quand même le vrai profil lève.

Sous pytest = `_pytest` importé dans CE process. Pas `PYTEST_CURRENT_TEST` : les sous-processus
d'un test l'héritent, y compris ceux qui jouent volontairement un process HORS pytest."""
from __future__ import annotations

import os
import sys
from pathlib import Path

VAR_VRAI_HOME = "BZ_TESTS_VRAI_HOME"


class EcritureDansLeVraiHome(RuntimeError):
    """Un test a visé le vrai `~/.bouzecode` : jamais toléré, jamais silencieux."""


def sous_pytest() -> bool:
    return "_pytest" in sys.modules


def vrai_dossier_bouzecode() -> Path:
    from bouzecode.paths import data_dir
    return data_dir(home=Path(os.environ.get(VAR_VRAI_HOME) or os.path.expanduser("~")))


def _normalise(chemin: Path) -> str:
    return os.path.normcase(os.path.realpath(chemin))


def refuser_le_vrai_home(chemin: Path) -> Path:
    """Rend `chemin` tel quel, sauf sous pytest s'il vit sous le vrai `~/.bouzecode`."""
    if not sous_pytest():
        return chemin
    interdit = _normalise(vrai_dossier_bouzecode())
    cible = _normalise(chemin)
    if cible == interdit or cible.startswith(interdit + os.sep):
        raise EcritureDansLeVraiHome(
            f"écriture sous pytest dans le VRAI {vrai_dossier_bouzecode()} : {chemin}. "
            "Le HOME du test n'est pas isolé (pytest_home_etanche absent ?) ou un chemin "
            "figé à l'import n'a pas été redirigé (production_isolation).")
    return chemin
