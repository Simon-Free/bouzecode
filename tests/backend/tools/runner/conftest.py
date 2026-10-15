# [desc] Enferme chaque pytest IMBRIQUÉ du répertoire dans le tmp de son test (rootdir, basetemp, cache, cwd). [/desc]
"""Ces tests-là ne se contentent pas de tourner : ils LANCENT un pytest complet.

`RunPythonTest` exécute `pytest <fichier>` dans un sous-process. Ce pytest-là hérite de
l'environnement du test : on lui passe, par `PYTEST_ADDOPTS`, les options de
`tests.pytest_imbrique.options_etanches`, et on place le test dans son `tmp_path` (cwd), si
bien qu'une cible sans pyproject y donne aussi son répertoire de travail à `RunPythonTest`.

Historique : ce conftest SÉRIALISAIT ces tests par un verrou fichier inter-workers, posé le
2026-07-30 contre « six rouges en 146 s sous `-n auto` », lus comme de la contention CPU. La
cause était ailleurs (mesuré le 2026-10-05) : sans rootdir à lui, le pytest imbriqué collectait
`%TEMP%` entier, 8 à 19 s par test même en série, et tombait sur les dossiers que les autres
pytest y créaient et supprimaient. Étanches, ils tournent en 1 à 3 s et en `-n 4`.
"""
from __future__ import annotations

import os

import pytest

from tests.pytest_imbrique import options_etanches


@pytest.fixture(autouse=True)
def _pytest_imbrique_etanche(tmp_path, monkeypatch):
    """Tout pytest lancé par ce test reste dans le `tmp_path` du test : cwd (donc rootdir et
    `confcutdir` pour une cible du tmp_path), basetemp et cache. Une cible du dépôt se désigne par
    un chemin ABSOLU : RunPythonTest remonte alors au pyproject du dépôt, qui reste son rootdir."""
    monkeypatch.chdir(tmp_path)
    options = " ".join(options_etanches(tmp_path))
    precedentes = os.environ.get("PYTEST_ADDOPTS", "")
    monkeypatch.setenv("PYTEST_ADDOPTS", f"{precedentes} {options}".strip())
