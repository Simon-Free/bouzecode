# [desc] Un test bouzecode() qui échoue affiche dans le rapport pytest la transcription de sa conversation simulée. [/desc]
"""Quand un test de conversation échoue, le rapport montre ce que les outils ont renvoyé.

On lance un VRAI pytest (sous-processus) sur deux tests de conversation écrits pour échouer :
l'un sur son assertion finale, l'autre parce que le modèle simulé n'a plus de réponse (le
harnais lève avant de rendre son résultat). Dans les deux cas, la sortie doit contenir la
transcription : appels d'outils, leur résultat réel, messages du harnais, raison de clôture.
"""
from __future__ import annotations

import locale
import os
import subprocess
import sys
import textwrap
from pathlib import Path

from tests.pytest_imbrique import options_etanches

RACINE = Path(__file__).resolve().parents[3]

TESTS_QUI_ECHOUENT = textwrap.dedent('''
    from tests.e2e_harness import bouzecode
    from tests.fake_llm import MockLLM

    METH = '<tool_use name="Methodology" id="m{n}"><param name="content">étape {n}</param></tool_use>'
    BASH = '<tool_use name="Bash" id="b1"><param name="command">echo SORTIE_OUTIL_42</param></tool_use>'


    def test_assertion_ratee_apres_un_bash():
        mock = MockLLM([METH.format(n=1) + BASH, "C'est fait."])
        result = bouzecode(["lance la commande"], mock_llm=mock)
        assert "réponse attendue" in result.last_reply


    def test_modele_simule_a_court_de_reponses():
        bouzecode(["lance la commande"], mock_llm=MockLLM([METH.format(n=1) + BASH]))
''')


def _pytest_sur(fichier: Path) -> str:
    # Encodage de sortie laissé à la locale : une console cp1252 ne doit pas illisibiliser la section.
    # rootdir, basetemp et cache dans le dossier du fichier : cf. tests.pytest_imbrique.
    #  Les DEUX bouts à la locale : un PYTHONIOENCODING/PYTHONUTF8 hérité du shell faisait écrire
    #  l'enfant en UTF-8 pendant que ce parent décodait en cp1252 (« rÃ©ponses »).
    locale_ = locale.getpreferredencoding(False)
    env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(RACINE / "src"), str(RACINE)]),
               PYTHONIOENCODING=locale_)
    env.pop("PYTHONUTF8", None)
    commande = [sys.executable, "-m", "pytest", str(fichier), "-p", "tests.conftest",
                "-o", "addopts=", "-p", "no:xdist", "--rootdir", str(fichier.parent),
                *options_etanches(fichier.parent), "-q"]
    sortie = subprocess.run(commande, cwd=fichier.parent, env=env, capture_output=True,
                            encoding=locale_, errors="replace", timeout=120)
    return sortie.stdout + sortie.stderr


def test_rapport_d_echec_montre_la_conversation_simulee(tmp_path):
    """Un test de conversation qui échoue affiche ses appels d'outils, leurs résultats et la clôture."""
    fichier = tmp_path / "test_conversation_qui_echoue.py"
    fichier.write_text(TESTS_QUI_ECHOUENT, encoding="utf-8")

    sortie = _pytest_sur(fichier)

    assert "2 failed" in sortie, sortie
    assert sortie.count("bouzecode() conversation") == 2, sortie
    # L'appel d'outil, abrégé, et ce que l'outil a VRAIMENT renvoyé.
    assert "-> Bash(command='echo SORTIE_OUTIL_42')" in sortie, sortie
    assert "<= Bash :" in sortie, sortie
    assert sortie.count("SORTIE_OUTIL_42") >= 4, sortie  # appel + résultat, dans chaque test
    # La demande de l'utilisateur et la raison de clôture.
    assert "[user] lance la commande" in sortie, sortie
    assert "close_reason : text_no_tools" in sortie, sortie
    # Le harnais a levé avant de rendre son résultat : la transcription est quand même là.
    assert "MockLLM : 1/1 réponses consommées" in sortie, sortie
    assert "la conversation ne s'est pas close" in sortie, sortie


def test_un_test_vert_n_affiche_aucune_transcription(tmp_path):
    """Un test de conversation qui passe n'alourdit pas la sortie."""
    fichier = tmp_path / "test_conversation_verte.py"
    fichier.write_text(TESTS_QUI_ECHOUENT.replace("réponse attendue", "fait"), encoding="utf-8")

    sortie = _pytest_sur(fichier)

    # Seul le test à court de réponses échoue encore : une seule transcription.
    assert "1 failed, 1 passed" in sortie, sortie
    assert sortie.count("bouzecode() conversation") == 1, sortie
    assert "close_reason : text_no_tools" not in sortie, sortie
