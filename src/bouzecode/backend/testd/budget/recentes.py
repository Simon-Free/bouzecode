# [desc] testd : dernières durées de chaque test (5 au plus, `test_durations/recentes/<dépôt>.json`) et leur médiane, base de la limite adaptative par test [/desc]
"""Le fichier des durées (`durations.py`) ne garde que la DERNIÈRE mesure de chaque test : il
ordonne et dimensionne les runs, et ses lecteurs (plugin compris) attendent un nombre. La limite
adaptative (cf. garde.limites) veut la durée HABITUELLE : une mesure aberrante (machine chargée,
premier lancement) ne doit ni tuer un test sain ni laisser 30 s à un test d'une seconde. On garde
donc à part les `GARDEES` dernières mesures, et on en prend la médiane."""
from __future__ import annotations

import json
import os
import statistics
import threading
from pathlib import Path

GARDEES = 5
_verrou = threading.Lock()


def fichier_recentes(historique: Path) -> Path:
    """À côté du fichier des durées, dans un sous-dossier (un `<dépôt>.json` par dépôt)."""
    dossier = historique.parent / "recentes"
    dossier.mkdir(parents=True, exist_ok=True)
    return dossier / historique.name


def _charger(fichier: Path) -> dict:
    return json.loads(fichier.read_text(encoding="utf-8")) if fichier.exists() else {}


def medianes(historique: Path) -> dict[str, float]:
    """{nodeid: médiane des dernières durées} ; un test jamais mesuré est absent."""
    return {nodeid: statistics.median(serie)
            for nodeid, serie in _charger(fichier_recentes(historique)).items() if serie}


def ajouter(historique: Path, mesures: dict) -> None:
    """Ajoute les durées d'un run (écriture atomique : d'autres jobs lisent le fichier)."""
    if not mesures:
        return
    with _verrou:
        fichier = fichier_recentes(historique)
        series = _charger(fichier)
        for nodeid, duree in mesures.items():
            series[nodeid] = [*series.get(nodeid, []), round(duree, 3)][-GARDEES:]
        provisoire = fichier.with_suffix(f".{os.getpid()}.tmp")
        provisoire.write_text(json.dumps(series, sort_keys=True), encoding="utf-8")
        os.replace(provisoire, fichier)
