# [desc] Après un run impacté (ou full=true du nightly), les échecs sont rejoués sur le merge-base (worktree jetable, cache par SHA) : NEW failures séparés des pre-existing on base ; vrai dépôt git dans tmp_path. [/desc]
"""Suite finale du 2026-10-13 : rien ne distinguait les échecs déjà présents sur develop des
nouveaux, et l'agent a « corrigé » un échec ancien en affaiblissant un test de sécurité. Le
2026-10-14, deux tests `always` sont rouges sur develop (demo `test_shared_settings.py`,
demoapp `test_no_dead_links.py`) : un run impacté ne doit pas les mettre au compte de l'agent."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from bouzecode.backend.tools.ops.test_runner import run_python_test

_FICHIERS = {
    "pyproject.toml": '[project]\nname = "depot"\nversion = "0"\n\n'
                      '[tool.pytest.ini_options]\ntestpaths = ["tests"]\npythonpath = ["src"]\n',
    ".gitignore": "__pycache__/\n.basetemp_imbrique/\n",
    ".bouzecode/tests.yaml": "impacted:\n  always: [tests/test_ancien.py]\n",
    "src/pkg/__init__.py": "",
    "src/pkg/a.py": "def f():\n    return 1\n",
    "tests/test_ancien.py": "def test_rouge_sur_develop():\n    assert False, 'deja rouge'\n",
    "tests/test_ok.py": "from pkg.a import f\n\ndef test_f():\n    assert f() == 1\n",
}


def _git(depot: Path, *args: str) -> str:
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=depot,
                          check=True, capture_output=True, text=True).stdout.strip()


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
    #  La branche casse test_f (code), ajoute un test rouge dans un fichier existant et un
    #  fichier de test nouveau : trois échecs NOUVEAUX, absents ou verts sur develop.
    (racine / "src/pkg/a.py").write_text("def f():\n    return 2\n")
    with open(racine / "tests/test_ok.py", "a", encoding="utf-8") as fichier:
        fichier.write("\ndef test_ajoute_rouge():\n    assert f() == 3\n")
    (racine / "tests/test_nouveau.py").write_text("def test_neuf():\n    assert 0\n")
    _git(racine, "add", ".")
    _git(racine, "commit", "-q", "-m", "travail")
    monkeypatch.chdir(racine)
    monkeypatch.setenv("BZ_NIGHTLY", "1")  # full=true : le chemin du build nightly
    return racine


def _section(resultat: str, titre: str) -> list[str]:
    """Les ids listés sous `titre (N) :` dans le résultat."""
    lignes = resultat.splitlines()
    debut = next(i for i, l in enumerate(lignes) if l.startswith(titre))
    nombre = int(lignes[debut].split("(", 1)[1].split(")", 1)[0])
    return [l.strip() for l in lignes[debut + 1:debut + 1 + nombre]]


def test_full_separe_nouveaux_et_anciens_echecs(depot):
    develop_avant = _git(depot, "rev-parse", "develop")
    resultat = run_python_test(full=True, parallel="off", timeout=120)
    assert sorted(_section(resultat, "NEW failures")) == [
        "tests/test_nouveau.py::test_neuf", "tests/test_ok.py::test_ajoute_rouge",
        "tests/test_ok.py::test_f"], resultat
    assert _section(resultat, "pre-existing on base develop") == [
        "tests/test_ancien.py::test_rouge_sur_develop"], resultat
    #  La base n'est jamais modifiée, le worktree jetable est retiré.
    assert _git(depot, "rev-parse", "develop") == develop_avant
    assert len(_git(depot, "worktree", "list").splitlines()) == 1


def test_resultats_de_base_en_cache_par_sha(depot):
    sha = _git(depot, "merge-base", "HEAD", "develop")
    run_python_test(full=True, parallel="off", timeout=120)
    cache = Path.home() / ".bouzecode" / "test_baselines" / "depot" / f"{sha}.json"
    contenu = json.loads(cache.read_text(encoding="utf-8"))
    assert contenu["tests/test_ancien.py::test_rouge_sur_develop"] == "failed"
    assert contenu["tests/test_ok.py::test_f"] == "passed"
    assert contenu["tests/test_nouveau.py::test_neuf"] == "absent"
    second = run_python_test(full=True, parallel="off", timeout=120)
    assert "0 id(s) rejoués" in second, second


def test_run_impacte_compare_aussi(depot):
    """always rouge sur develop + code changé : l'échec always est pre-existing, pas NEW."""
    resultat = run_python_test(parallel="off", timeout=120)
    assert resultat.startswith("impacted:"), resultat
    assert _section(resultat, "pre-existing on base develop") == [
        "tests/test_ancien.py::test_rouge_sur_develop"], resultat
    assert "tests/test_ok.py::test_f" in _section(resultat, "NEW failures")


def test_run_cible_ne_compare_pas(depot):
    resultat = run_python_test(targets=["tests/test_ancien.py"], parallel="off", timeout=120)
    assert "pre-existing" not in resultat and "1 failed" in resultat


def test_erreur_de_setup_sur_la_base_est_ancienne(depot):
    """Une erreur de setup déjà présente sur develop (environnement) n'est pas NEW."""
    _git(depot, "checkout", "-q", "develop")
    (depot / "tests/test_setup_casse.py").write_text(
        "import pytest\n\n@pytest.fixture\ndef env():\n    raise RuntimeError('env absent')\n\n"
        "def test_a_besoin_d_env(env):\n    pass\n", encoding="utf-8")
    _git(depot, "add", "tests/test_setup_casse.py")
    _git(depot, "commit", "-q", "-m", "erreur de setup sur develop")
    _git(depot, "checkout", "-q", "travail")
    _git(depot, "merge", "-q", "--no-edit", "develop")
    resultat = run_python_test(full=True, parallel="off", timeout=120)
    erreur = "tests/test_setup_casse.py::test_a_besoin_d_env"
    assert erreur in _section(resultat, "pre-existing on base develop"), resultat
    assert erreur not in _section(resultat, "NEW failures"), resultat
    sha = _git(depot, "merge-base", "HEAD", "develop")
    cache = Path.home() / ".bouzecode" / "test_baselines" / "depot" / f"{sha}.json"
    assert json.loads(cache.read_text(encoding="utf-8"))[erreur] == "error"
