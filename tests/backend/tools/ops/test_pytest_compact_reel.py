# [desc] Compaction des sorties pytest sur de VRAIS runs (mini projet en sous-process) : vert = verdict seul, rouge = l'essentiel de chaque échec, sections de plugin bornées, vues `show`. [/desc]
"""Chaque caractère du résultat RunPythonTest est payé en tokens frais.

Constat du 2026-10-07 : 8 723 car. renvoyés pour 175 tests verts — une section de plugin
inconnue (400 lignes) collée au « warnings summary », gardé même au vert, plus 15 durées.
Ici chaque scénario lance un vrai pytest sur un mini projet et passe sa sortie au rendu.
"""
from __future__ import annotations

import subprocess
import sys

import pytest

from bouzecode.backend.tools.ops.pytest_compact import compact_pytest_output, rendu_pytest

CONFTEST = '''
def pytest_terminal_summary(terminalreporter):
    terminalreporter.section("rapport du plugin maison")
    for i in range(30):
        terminalreporter.write_line(f"ligne_de_plugin_{i}")
'''
TEST_VERT = '''
import time, warnings, pytest

@pytest.mark.parametrize("n", range(20))
def test_vert(n):
    warnings.warn("AVERTISSEMENT_REPETE", DeprecationWarning)
    assert n >= 0

def test_lent():
    time.sleep(1.05)
'''
TEST_ROUGE = '''
import warnings

def aide(total):
    assert total == 42, "TOTAL_ATTENDU_42"

def test_total():
    for i in range(300):
        print(f"journal ligne {i} : tout va bien")
    warnings.warn("AVERTISSEMENT_DU_FICHIER_ROUGE", UserWarning)
    aide(41)

def test_ok():
    assert True
'''
TEST_COLLECTE = "import module_absent_xyz\n\ndef test_jamais():\n    pass\n"


@pytest.fixture(scope="module")
def projet(tmp_path_factory):
    racine = tmp_path_factory.mktemp("mini")
    (racine / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    (racine / "conftest.py").write_text(CONFTEST, encoding="utf-8")
    (racine / "test_vert.py").write_text(TEST_VERT, encoding="utf-8")
    (racine / "test_rouge.py").write_text(TEST_ROUGE, encoding="utf-8")
    (racine / "test_collecte.py").write_text(TEST_COLLECTE, encoding="utf-8")
    return racine


def _pytest(racine, *cibles) -> str:
    proc = subprocess.run([sys.executable, "-m", "pytest", "-v", "-p", "no:cacheprovider",
                           "--durations=15", *cibles], cwd=racine, capture_output=True,
                          text=True, encoding="utf-8", errors="replace", timeout=60)
    return proc.stdout + proc.stderr


@pytest.fixture(scope="module")
def sortie_verte(projet):
    return _pytest(projet, "test_vert.py")


@pytest.fixture(scope="module")
def sortie_rouge(projet):
    return _pytest(projet, "test_rouge.py", "test_vert.py")


@pytest.fixture(autouse=True)
def _sorties_d_outil(tmp_path, monkeypatch):
    monkeypatch.setenv("BOUZECODE_TOOL_OUTPUT_DIR", str(tmp_path / "tool_outputs"))


def test_vert_avec_section_inconnue_rend_le_verdict_le_test_lent_et_la_section_bornee(sortie_verte):
    rendu = rendu_pytest(sortie_verte)
    assert "21 passed" in rendu
    assert "test_vert.py::test_lent" in rendu and "tests lents" in rendu
    assert "AVERTISSEMENT_REPETE" not in rendu and "warnings summary" not in rendu
    assert "PASSED" not in rendu and "test_vert[3]" not in rendu
    assert "=== rapport du plugin maison ===" in rendu and "ligne_de_plugin_0" in rendu
    assert "ligne_de_plugin_29" not in rendu and "(+22 lignes)" in rendu
    assert "full output saved to:" in rendu  # section coupée : la sortie complète est pointée
    assert len(rendu) < 1100, rendu


def test_vert_sans_plugin_rend_le_verdict_et_les_tests_lents_seulement(projet):
    rendu = rendu_pytest(_pytest(projet, "--noconftest", "test_vert.py"))
    lignes = rendu.splitlines()
    assert lignes[:3] == ["tests lents (≥ 1 s) :", lignes[1], ""], rendu
    assert lignes[1].endswith("call test_vert.py::test_lent")
    assert lignes[3].startswith("21 passed, 20 warnings in ") and len(lignes) == 4, rendu


def test_echec_d_assertion_garde_l_essentiel_et_rien_du_vert(sortie_rouge):
    rendu = rendu_pytest(sortie_rouge)
    assert "FAILED test_rouge.py::test_total" in rendu
    assert "TOTAL_ATTENDU_42" in rendu and "assert 41 == 42" in rendu
    assert "aide(41)" in rendu, "la ligne du test qui échoue"
    assert "test_rouge.py:5: AssertionError" in rendu, "la frame finale"
    assert "journal ligne 0" in rendu and "journal ligne 150" not in rendu, "capture bornée"
    assert "1 failed, 22 passed" in rendu
    assert "AVERTISSEMENT_DU_FICHIER_ROUGE" in rendu, "warning du fichier en échec"
    assert "AVERTISSEMENT_REPETE" not in rendu, "warning d'un fichier vert : hors sujet"
    assert "tests lents" not in rendu and "test_ok" not in rendu
    chemin = rendu.split("full output saved to: ", 1)[1].split("]", 1)[0]
    assert "journal ligne 299" in open(chemin, encoding="utf-8").read()
    assert len(rendu) < 3000, len(rendu)


def test_erreur_de_collecte_toujours_montree(projet):
    rendu = rendu_pytest(_pytest(projet, "test_collecte.py"))
    assert "ERROR collecting test_collecte.py" in rendu
    assert "ModuleNotFoundError" in rendu and "module_absent_xyz" in rendu
    assert "Interrupted: 1 error during collection" in rendu
    assert "1 error" in rendu.splitlines()[-2]


def test_cible_absente_garde_la_raison_du_no_tests_ran(projet):
    rendu = rendu_pytest(_pytest(projet, "absent_xyz.py"))
    assert "ERROR: file or directory not found: absent_xyz.py" in rendu
    assert "no tests ran" in rendu


def test_show_warnings_dedoublonne_et_compte(sortie_verte):
    """20 occurrences : un seul message, le compte donné par pytest ; vert sans `show` : rien."""
    rendu = rendu_pytest(sortie_verte, ("warnings",))
    assert rendu.count("DeprecationWarning: AVERTISSEMENT_REPETE") == 1
    assert "test_vert.py: 20 warnings" in rendu


def test_warnings_repetes_au_meme_emplacement_comptes_une_fois():
    """Forme réelle du 2026-10-07 : quatre fois le même emplacement pour un même message."""
    from bouzecode.backend.tools.ops.pytest_sections import warnings_dedoublonnes
    bloc = ["t\\a.py:19"] * 4 + ["  C:\\x\\t\\a.py:19: PytestUnknownMarkWarning: Unknown mark",
                                 "    @pytest.mark.timeout(90)", ""]
    rendu = warnings_dedoublonnes(bloc + ["t\\b.py:97"] * 4 + bloc[4:])
    assert rendu.count("PytestUnknownMarkWarning") == 1
    assert "t\\a.py:19, t\\b.py:97 (×8)" in rendu and "C:\\x" not in rendu


def test_show_durations_passed_et_full(sortie_verte):
    assert "durées :" in rendu_pytest(sortie_verte, ("durations",))
    passes = rendu_pytest(sortie_verte, ("passed",))
    assert "tests passés (21)" in passes and "test_vert.py::test_vert[19]" in passes
    assert "test session starts" in rendu_pytest(sortie_verte, ("full",))


def test_sortie_non_pytest_inchangee():
    texte = "rien à voir avec pytest\n" * 5
    assert compact_pytest_output(texte) is texte
    assert rendu_pytest(texte) == texte
