# [desc] Plugin pytest injecté par testd : neutralise les relances automatiques (marqueur `flaky(reruns=…)`, `--reruns`) et inscrit les tests marqués dans les événements, pour que le rapport les nomme [/desc]
"""Chargé par `-p _bz_sans_relance` (même dossier que `_bz_testd_plugin`). Autonome : il tourne
dans le venv du PROJET testé.

Mesuré le 2026-10-14 : un vrai échec (dépendance absente) dans un test marqué
`flaky(reruns=2)` (demo, tests/browser/conftest.py) a coûté 3 × 120 s + le reste, 420 s. Un
test qui échoue doit échouer UNE fois, vite ; la seule relance permise est celle du démon quand
son navigateur chaud meurt (annoncée dans le rapport).

`-p no:rerunfailures` (posé par RunPythonTest) suffit à couper le marqueur — vérifié avec
pytest-rerunfailures 16.1 — mais il n'est pas posé si l'appelant passe `--reruns`, ni quand un
conftest charge le plugin sous un autre nom (`pytest_plugins = ["pytest_rerunfailures"]`). Ici :
`force_reruns = 0` (pytest-rerunfailures ≥ 14, prioritaire sur tout le reste), et à défaut un
marqueur `flaky(reruns=0)` posé AU PLUS PRÈS de chaque test marqué (c'est le plus proche que lit
le plugin). `max_runs=1` couvre aussi le paquet `flaky`."""
import json
import os
import time
from pathlib import Path

import pytest

_SANS_RELANCE = {"reruns": 0, "max_runs": 1, "min_passes": 1}


def _ecrire(evenement: dict) -> None:
    dossier = os.environ.get("BZ_TESTD_EVENTS")
    if not dossier:
        return
    evenement["t"] = time.time()
    with open(Path(dossier) / f"{os.getpid()}.jsonl", "a", encoding="utf-8") as fichier:
        fichier.write(json.dumps(evenement) + "\n")


def pytest_configure(config):
    #  Déclaré pour `--strict-markers` quand le plugin des relances est coupé (`-p no:…`).
    config.addinivalue_line("markers", "flaky: relances automatiques (neutralisées par testd)")
    option = config.option
    if getattr(option, "reruns", None):
        _ecrire({"e": "relances", "option": f"--reruns {option.reruns}"})
        option.reruns = 0
    if hasattr(option, "force_reruns"):
        option.force_reruns = 0


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(session, config, items):
    """Après les conftest : celui de demo pose `flaky` dans ce même hook. Écrit aussi par
    les workers xdist (ce sont eux qui collectent) ; le démon dédoublonne."""
    marques = []
    for item in items:
        marqueur = item.get_closest_marker("flaky")
        if marqueur is None or marqueur.kwargs == _SANS_RELANCE:
            continue
        marques.append(item.nodeid)
        item.add_marker(pytest.mark.flaky(**_SANS_RELANCE), append=False)
    if marques:
        _ecrire({"e": "flaky", "ids": marques})
