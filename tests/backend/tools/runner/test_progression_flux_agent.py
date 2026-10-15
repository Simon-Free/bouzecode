# [desc] Progression en direct de RunPythonTest dans le flux de l'agent qui l'execute : ligne du spinner pour main, fiche/onglet/barre pour un sous-agent, rien chez main. Vrai pytest, vrai spinner. [/desc]
"""Regression du 2026-10-12 : plus aucune progression nulle part.

`tqdm` (barre de main, sur stderr) n'etait qu'une dependance transitive d'openai 2.x : parti
avec openai 3, la barre etait sautee sans erreur. Et ecrite a cote du spinner, elle etait
de toute facon ecrasee a chaque frame. Ici : le vrai outil enregistre, un vrai pytest de
6 tests lents, le vrai spinner sur un terminal en memoire ; on attend un ETAT observable
(texte a l'ecran pendant que l'outil tourne), jamais une duree fixe.
"""
from __future__ import annotations

import io
import sys
import threading
import time
from types import SimpleNamespace

import pytest

import bouzecode.backend.tools.registration  # noqa: F401  (enregistre RunPythonTest)
from bouzecode.backend.core.tool_registry import get_tool
from bouzecode.backend.multi_agent.en_process.fiche import FicheAgent
from bouzecode.backend.multi_agent.en_process.registre import RegistreAgents
from bouzecode.ui import spinner
from bouzecode.ui.barre_agents import rendu
from bouzecode.ui.barre_agents.clavier import Navigation


@pytest.fixture
def tests_lents(tmp_path):
    corps = "import time\n" + "".join(
        f"def test_{i}():\n    time.sleep(0.4)\n" for i in range(6))
    fichier = tmp_path / "test_lents.py"
    fichier.write_text(corps, encoding="utf-8")
    return fichier


@pytest.fixture
def registre():
    registre = RegistreAgents()
    registre.declarer_principal(SimpleNamespace(messages=[]), "claude-sonnet-4-5")
    registre.ajouter(FicheAgent(id="a1", description="tests", activite="RunPythonTest",
                                state=SimpleNamespace(messages=[])))
    return registre


@pytest.fixture
def terminal(monkeypatch):
    """stdout (ou dessine le spinner) et stderr en memoire, spinner lance comme a un ToolStart."""
    ecran, erreurs = io.StringIO(), io.StringIO()
    monkeypatch.setattr(sys, "stdout", ecran)
    monkeypatch.setattr(sys, "stderr", erreurs)
    monkeypatch.setattr(rendu, "_source_pied", None)
    spinner._start_tool_spinner()
    yield ecran, erreurs
    spinner._stop_tool_spinner()


def _lancer(fichier, config) -> threading.Thread:
    outil = get_tool("RunPythonTest")
    params = {"targets": [str(fichier)], "parallel": "off", "timeout": 60, "no_sync": True}
    fil = threading.Thread(target=outil.func, args=(params, config), daemon=True)
    fil.start()
    return fil


def _attendre(condition, quoi: str, delai: float = 30.0) -> None:
    fin = time.monotonic() + delai
    while time.monotonic() < fin:
        if condition():
            return
        time.sleep(0.05)
    raise AssertionError(f"jamais atteint : {quoi}")


def test_main_voit_la_progression_en_direct_dans_la_ligne_du_spinner(tests_lents, registre, terminal):
    ecran, erreurs = terminal
    fil = _lancer(tests_lents, {"_tui_agents": registre})

    _attendre(lambda: "pytest: " in ecran.getvalue(), "progression dans la ligne du spinner")
    assert fil.is_alive(), "la progression doit paraitre PENDANT le run, pas apres"
    fil.join(30)
    _attendre(lambda: "pytest: 6/6" in ecran.getvalue(), "6/6 dessine par le spinner")
    assert "pytest" not in erreurs.getvalue()  # une seule ligne vivante, pas de barre a cote


def test_sous_agent_progression_dans_sa_fiche_et_sa_barre_jamais_chez_main(
        tests_lents, registre, terminal):
    ecran, erreurs = terminal
    fil = _lancer(tests_lents, {"_tui_agents": registre, "_tui_moi": "a1"})

    _attendre(lambda: registre.fiche("a1").progression.startswith("pytest: "),
              "progression dans la fiche du sous-agent")
    assert fil.is_alive()
    assert "pytest: " in rendu.texte(registre, Navigation())  # visible depuis la barre
    fil.join(30)

    assert "6/6" in registre.fiche("a1").progression
    assert "pytest" not in ecran.getvalue()  # la ligne vivante de main reste la sienne
    assert "pytest" not in erreurs.getvalue()
