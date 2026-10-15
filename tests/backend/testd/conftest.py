# [desc] Tests testd : pytest imbriqués étanches dans le tmp du test, et un VRAI démon par test (dossier testd jetable, port éphémère), arrêté à la fin [/desc]
from __future__ import annotations

import json
import os
import time

import pytest

from bouzecode.backend.testd.common import tuer_arbre

from tests.pytest_imbrique import options_etanches


@pytest.fixture(autouse=True)
def _pytest_imbrique_etanche(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    options = " ".join(options_etanches(tmp_path))
    monkeypatch.setenv("PYTEST_ADDOPTS", f"{os.environ.get('PYTEST_ADDOPTS', '')} {options}".strip())


@pytest.fixture
def demon(tmp_path, monkeypatch):
    """Démon réel isolé : son dossier, 1 worker (la file se voit), inactivité courte."""
    monkeypatch.setenv("BZ_TESTD", "1")
    monkeypatch.setenv("BZ_TESTD_HOME", str(tmp_path / "testd_home"))
    monkeypatch.setenv("BZ_TESTD_WORKERS_TOTAL", "1")
    monkeypatch.setenv("BZ_TESTD_IDLE_S", "120")
    from bouzecode.backend.testd import client
    yield client
    _arreter_pour_de_bon(client, tmp_path / "testd_home" / "daemon.json")


def _arreter_pour_de_bon(client, fichier) -> None:
    """Arrêt propre ; s'il ne répond pas en 15 s, son arbre est tué (navigateurs compris) :
    aucun test ne doit laisser de démon derrière lui."""
    info = json.loads(fichier.read_text(encoding="utf-8")) if fichier.exists() else None
    client.arreter_demon()
    fin = time.monotonic() + 15
    while fichier.exists() and time.monotonic() < fin:
        time.sleep(0.2)
    if info and fichier.exists():
        tuer_arbre(info["pid"])



def pytest_configure(config):
    config.addinivalue_line("markers", "browser_integration: vrai navigateur (Playwright installé requis)")
