# [desc] `pytest --only-changed` rejoue les tests dont le code couvert a bougé dans git, et eux seuls. [/desc]
"""Comportement vu par le développeur qui tape `pytest --only-changed` : chaque test ouvre un
vrai dépôt git jetable, y pose deux fichiers de test qui déclarent ce qu'ils couvrent, modifie
un fichier applicatif, et lit dans la sortie de pytest ce qui a été rejoué."""
import os
import subprocess

import pytest

pytest_plugins = ["pytester"]

PLUGIN = "bouzecode.web_v2.tests.pytest_only_changed"
BASE = "src/bouzecode/web_v2"

TEST_BUREAU = '''
import pytest
pytestmark = pytest.mark.couvre("static/js/bureau/**", "routes/work/micros.py")
def test_bureau():
    pass
'''
TEST_AGENTS = '''
import pytest
pytestmark = pytest.mark.couvre("static/js/conversations/**")
def test_agents():
    pass
'''
TEST_SANS_MARQUEUR = '''
def test_libre():
    pass
'''


def _git(cwd, *args):
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    subprocess.run(["git", *args], cwd=cwd, env=env, check=True, capture_output=True)


def _ecrire(root, rel, texte="x\n"):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(texte, encoding="utf-8")


@pytest.fixture
def depot(pytester, monkeypatch):
    #  Le pytest imbriqué écrit sur un tube : sans mode UTF-8, Windows l'encode en cp1252 et la
    #  sortie (« modifiés », « → ») n'est plus lisible par le parent, qui la décode en UTF-8.
    monkeypatch.setenv("PYTHONUTF8", "1")
    monkeypatch.setenv("PYTHONIOENCODING", "utf-8")
    root = pytester.path
    _ecrire(root, f"{BASE}/static/js/bureau/liste.js")
    _ecrire(root, f"{BASE}/static/js/conversations/liste.js")
    _ecrire(root, f"{BASE}/routes/work/micros.py")
    _ecrire(root, f"{BASE}/static/ds.css")
    _ecrire(root, "e2e/test_bureau.py", TEST_BUREAU)
    _ecrire(root, "e2e/test_agents.py", TEST_AGENTS)
    _ecrire(root, "e2e/test_libre.py", TEST_SANS_MARQUEUR)
    _git(root, "init", "-q", "-b", "main")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "base")
    return root


def _lancer(pytester, *args):
    return pytester.runpytest_subprocess("-p", PLUGIN, "e2e", *args)


def test_sans_l_option_tout_est_rejoue(pytester, depot):
    _ecrire(depot, f"{BASE}/static/js/bureau/liste.js", "modifié\n")
    res = _lancer(pytester)
    res.assert_outcomes(passed=3)


def test_modifier_le_js_du_bureau_ne_rejoue_que_le_bureau_et_les_tests_non_declares(pytester, depot):
    _ecrire(depot, f"{BASE}/static/js/bureau/liste.js", "modifié\n")
    res = _lancer(pytester, "--only-changed")
    res.assert_outcomes(passed=2, deselected=1)
    res.stdout.fnmatch_lines(["*only-changed : * fichiers modifiés → 2 tests gardés / 3*"])


def test_un_fichier_nouveau_non_suivi_compte_comme_modifie(pytester, depot):
    _ecrire(depot, f"{BASE}/static/js/conversations/nouveau.js")
    res = _lancer(pytester, "--only-changed", "-v")
    res.stdout.fnmatch_lines(["*test_agents.py::test_agents PASSED*"])
    res.assert_outcomes(passed=2, deselected=1)


def test_toucher_le_design_system_rejoue_tout(pytester, depot):
    _ecrire(depot, f"{BASE}/static/ds.css", "modifié\n")
    res = _lancer(pytester, "--only-changed")
    res.assert_outcomes(passed=3)
    res.stdout.fnmatch_lines(["*chemin global*"])


def test_modifier_le_fichier_de_test_lui_meme_le_rejoue(pytester, depot):
    _ecrire(depot, "e2e/test_agents.py", TEST_AGENTS + "\n# retouche\n")
    res = _lancer(pytester, "--only-changed", "-v")
    res.stdout.fnmatch_lines(["*test_agents.py::test_agents PASSED*"])
    res.assert_outcomes(passed=2, deselected=1)


def test_rien_de_modifie_ne_garde_que_les_tests_non_declares(pytester, depot):
    res = _lancer(pytester, "--only-changed")
    res.assert_outcomes(passed=1, deselected=2)


def test_avec_une_ref_les_commits_de_la_branche_comptent(pytester, depot):
    _git(depot, "checkout", "-q", "-b", "travail")
    _ecrire(depot, f"{BASE}/routes/work/micros.py", "modifié\n")
    _git(depot, "commit", "-qam", "micros")
    sans_ref = _lancer(pytester, "--only-changed")
    sans_ref.assert_outcomes(passed=1, deselected=2)
    avec_ref = _lancer(pytester, "--only-changed=main", "-v")
    avec_ref.stdout.fnmatch_lines(["*test_bureau.py::test_bureau PASSED*"])
    avec_ref.assert_outcomes(passed=2, deselected=1)


def test_un_chemin_pris_pour_une_ref_est_refuse_avec_une_explication(pytester, depot):
    res = pytester.runpytest_subprocess("-p", PLUGIN, "--only-changed", "e2e")
    assert res.ret != 0
    res.stderr.fnmatch_lines(["*--only-changed=REF*"])


def test_un_glob_qui_ne_designe_plus_aucun_fichier_est_signale(pytester, depot):
    _ecrire(depot, "e2e/test_perime.py", '''
import pytest
pytestmark = pytest.mark.couvre("routes/work/bureau_v2.py")
def test_perime():
    pass
''')
    res = _lancer(pytester, "--only-changed")
    res.stdout.fnmatch_lines(["*ATTENTION, globs couvre() qui ne désignent aucun fichier*routes/work/bureau_v2.py*"])
