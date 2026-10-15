# [desc] Bash refuse pytest (toutes les formes relevées le 2026-10-13) et montre l'appel RunPythonTest équivalent ; `# allow-raw-pytest: <raison>` laisse passer. [/desc]
"""pytest passe par RunPythonTest, pas par le Bash.

Mesuré le 2026-10-13 (sessions bouzecode, tutoriel DEMOAPP) : 307 lancements de pytest par le Bash
contre 13 par RunPythonTest. Les briefs de l'orchestrateur prescrivaient
`$env:PYTHONPATH=…; python -m pytest …` et les sous-agents recopiaient — alors que
RunPythonTest met déjà le `src` du worktree en tête de PYTHONPATH. La suite finale, lancée
`| Select-Object -Last 40`, a laissé l'agent aveugle 50 minutes.
"""
from __future__ import annotations

import sys

import pytest

from bouzecode.backend.tools.ops.pytest_shell_guard import refus_pytest_shell
from bouzecode.backend.tools.ops.shell_search import bash_handler


@pytest.mark.parametrize("commande", [
    "pytest tests/test_x.py -q",
    "py.test tests",
    "python -m pytest tests/inexistant -n 4",
    "python3 -m pytest",
    '$env:PYTHONPATH="C:\\wt\\src"; python -m pytest tests/test_x.py | Select-Object -Last 40',
    "cd C:\\wt && .venv\\Scripts\\python.exe -m pytest tests/test_x.py -x",
    "PYTHONPATH=src python -m pytest tests/test_x.py",
    "& C:\\Users\\u\\proj\\.venv\\Scripts\\python.exe -m pytest tests/test_x.py",
    "& $py -m pytest tests/inexistant -q",
    "uv run pytest tests/test_x.py",
    "uv run --directory C:\\wt python -m pytest tests",
    ".venv/bin/pytest tests/test_x.py",
    "C:\\wt\\.venv\\Scripts\\pytest.exe tests\\test_x.py",
])
def test_pytest_lance_par_le_bash_est_refuse(commande):
    #  La fonction de garde directement : avant le correctif, passer par le Bash aurait
    #  EXÉCUTÉ ces commandes (dont `uv run`, qui fabrique un venv).
    resultat = refus_pytest_shell(commande)
    assert "RunPythonTest(" in resultat, resultat
    assert "allow-raw-pytest" in resultat


def test_le_bash_applique_la_garde_avant_toute_execution(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for mode in ({}, {"background": True}, {"deferred": True}):
        resultat = bash_handler({"command": "python -m pytest tests/inexistant -q", **mode}, {})
        assert "RunPythonTest(" in resultat, (mode, resultat)


def test_le_refus_montre_l_appel_equivalent_avec_cibles_et_filtres():
    resultat = refus_pytest_shell((
        '$env:PYTHONPATH="C:\\wt\\src"; python -m pytest tests/test_a.py '
        'tests/test_b.py::test_c -k "lent and not web" -m slow -n 4 -q'))
    assert "RunPythonTest(targets=['tests/test_a.py', 'tests/test_b.py::test_c'], " \
           "keyword='lent and not web', marker='slow')" in resultat, resultat


@pytest.mark.parametrize("redirection", [
    "*> $env:TEMP\\solo10_red.txt", "> out.txt", ">> out.txt", "2>&1", "2> err.txt",
    "2>$null", "*>$env:TEMP\\r.txt", "1> out.txt 2>&1", "| Select-Object -Last 40",
    "2>&1 | Tee-Object -FilePath r.txt",
])
def test_les_redirections_du_shell_ne_deviennent_pas_des_cibles(redirection):
    """Session de4d1304 (2026-10-14) : `*> $env:TEMP\\solo10_red.txt` devenait deux `targets`."""
    resultat = refus_pytest_shell(
        f"python -m pytest tests\\focus\\x.py -rA -q -p no:cacheprovider {redirection}")
    assert "RunPythonTest(targets=['tests\\\\focus\\\\x.py'])." in resultat, resultat


def test_sans_cible_l_equivalent_est_la_selection_impactee():
    resultat = refus_pytest_shell("python -m pytest -q")
    assert "RunPythonTest()" in resultat


@pytest.mark.parametrize("commande", [
    "grep -rn pytest src",
    'git commit -m "test: pytest plus rapide"',
    "Select-String -Path pyproject.toml -Pattern pytest",
    "pip show pytest-xdist",
])
def test_une_commande_qui_parle_de_pytest_sans_le_lancer_passe(commande):
    assert refus_pytest_shell(commande) == ""


def test_echappatoire_explicite_avec_raison_laisse_passer(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    exe = f'& "{sys.executable}"' if sys.platform == "win32" else f'"{sys.executable}"'
    resultat = bash_handler({"command": (
        f"{exe} -m pytest --version  # allow-raw-pytest: sonde de version du venv")}, {})
    assert "RunPythonTest(" not in resultat
    assert "pytest" in resultat.lower()


def test_echappatoire_sans_raison_ne_suffit_pas():
    resultat = refus_pytest_shell("python -m pytest tests # allow-raw-pytest:")
    assert "RunPythonTest(" in resultat
