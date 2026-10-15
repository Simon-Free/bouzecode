# [desc] RunPythonTest() sans cible lance les tests impactés par les changements de la branche (git diff depuis develop + non commité + non suivi) : testmon pour le Python, `.bouzecode/tests.yaml` pour le reste, always, slow écartés ; vrai dépôt git dans tmp_path. [/desc]
"""Avant : `RunPythonTest()` sans cible était refusé, et l'agent passait par le Bash.
Maintenant c'est le défaut utile : les tests que la branche peut avoir cassés, et rien d'autre.
Chaque test monte un VRAI dépôt git (branche develop puis branche de travail) et appelle le vrai
outil ; la base testmon, quand il en faut une, est construite par un vrai `pytest --testmon`."""
from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from bouzecode.backend.tools.ops.test_runner import run_python_test

_YAML = textwrap.dedent("""\
    impacted:
      always: [tests/security]
      map:
        - paths: ["src/pkg/templates/**"]
          tests: ["tests/test_page*.py"]
        - paths: ["src/pkg/data/**"]
          tests: ["tests/lents"]
      slow: ["tests/lents/test_lent.py"]
    browser:
      marker: browser
    app_server:
      command: ["{python}", "run.py"]
""")

_FICHIERS = {
    "pyproject.toml": '[project]\nname = "depot"\nversion = "0"\n\n'
                      '[tool.pytest.ini_options]\ntestpaths = ["tests"]\npythonpath = ["src"]\n',
    ".gitignore": ".testmondata*\n__pycache__/\n.basetemp_imbrique/\n",
    ".bouzecode/tests.yaml": _YAML,
    "src/pkg/__init__.py": "",
    "src/pkg/a.py": "def f():\n    return 1\n",
    "src/pkg/b.py": "def g():\n    return 2\n",
    "src/pkg/templates/page.html": "<p>page</p>\n",
    "src/pkg/data/d.json": "{}\n",
    "tests/test_a.py": "from pkg.a import f\n\ndef test_f():\n    assert f() == 1\n",
    "tests/test_b.py": "from pkg.b import g\n\ndef test_g():\n    assert g() == 2\n",
    "tests/test_page.py": "def test_page():\n    assert True\n",
    "tests/security/test_scan.py": "def test_scan():\n    assert True\n",
    "tests/lents/test_lent.py": "def test_lent():\n    assert True\n",
    "tests/lents/test_rapide.py": "def test_rapide():\n    assert True\n",
}


def _git(depot: Path, *args: str) -> str:
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=depot,
                          check=True, capture_output=True, text=True).stdout


@pytest.fixture
def depot(tmp_path, monkeypatch):
    racine = tmp_path / "depot"
    for nom, contenu in _FICHIERS.items():
        (racine / nom).parent.mkdir(parents=True, exist_ok=True)
        (racine / nom).write_text(contenu, encoding="utf-8")
    _git(racine, "init", "-q", "-b", "develop")
    _git(racine, "add", ".")
    _git(racine, "commit", "-q", "-m", "base")
    _git(racine, "checkout", "-q", "-b", "travail")
    monkeypatch.chdir(racine)
    return racine


def _lancer(**options) -> str:
    return run_python_test(parallel="off", timeout=120, **options)


def _construire_base_testmon(depot: Path) -> None:
    env = {**os.environ, "PYTHONPATH": str(depot / "src")}
    sortie = subprocess.run([sys.executable, "-m", "pytest", "--testmon", "-q", "-p", "no:randomly"],
                            cwd=depot, env=env, capture_output=True, text=True, timeout=120)
    assert (depot / ".testmondata").exists(), sortie.stdout + sortie.stderr


def test_rien_de_modifie_rien_lance(depot):
    resultat = _lancer()
    premiere = resultat.splitlines()[0]
    assert premiere.startswith("impacted:") and "rien" in premiere, resultat
    assert "test session starts" not in resultat and "\n$ " not in resultat


def test_template_modifie_lance_les_tests_mappes_et_always(depot):
    (depot / "src/pkg/templates/page.html").write_text("<p>changé</p>\n")
    resultat = _lancer()
    premiere = resultat.splitlines()[0]
    assert premiere.startswith("impacted:") and "map 1" in premiere and "always 1" in premiere
    assert "2 passed" in resultat, resultat


def test_fichier_non_suivi_et_commit_de_branche_comptent(depot):
    (depot / "src/pkg/templates/nouveau.html").write_text("<p>neuf</p>\n")
    (depot / "src/pkg/data/d.json").write_text('{"x": 1}\n')
    _git(depot, "commit", "-q", "-am", "donnees")
    resultat = _lancer()
    assert "from 2 changed files" in resultat.splitlines()[0], resultat
    assert "--deselect tests/lents/test_lent.py" in resultat
    assert "3 passed, 1 deselected" in resultat, resultat


def test_testmon_selectionne_les_tests_du_module_modifie(depot):
    _construire_base_testmon(depot)
    (depot / "src/pkg/a.py").write_text("def f():\n    return 1  # changé\n")
    resultat = _lancer()
    premiere = resultat.splitlines()[0]
    assert "1 tests" in premiere and "testmon 1" in premiere, resultat
    assert "2 passed in" in resultat, resultat  # test_f + always ; test_b jamais lancé


def test_sans_base_testmon_repli_sur_le_mapping_et_le_dit(depot):
    (depot / "src/pkg/a.py").write_text("def f():\n    return 1  # changé\n")
    (depot / "tests/test_b.py").write_text("def test_g():\n    assert 2 == 2\n")
    resultat = _lancer()
    premiere = resultat.splitlines()[0]
    assert "testmon absent" in premiere and "test files 1" in premiere, premiere
    assert "unmapped 1" in premiere
    assert "2 passed" in resultat, resultat


def test_une_cible_explicite_ne_passe_pas_par_la_selection(depot):
    resultat = _lancer(targets=["tests/lents/test_lent.py"])
    assert not resultat.startswith("impacted:")
    assert "1 passed" in resultat
