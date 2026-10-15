# [desc] RunPythonTest guard rails on a real mini project: default -n 4, `auto` refused, full=true refused outside the nightly (BZ_NIGHTLY=1), --durations added once. [/desc]
"""RunPythonTest ne doit plus pousser les agents vers de mauvais lancements.

Constat du 2026-09-29 : un agent chargé d'optimiser la suite a lancé `-n auto` (20 workers)
dès son premier run — c'était le défaut de l'outil, et sa description disait « Sans cible :
toute la suite ». Chaque test ici appelle le VRAI outil (fonction ou outil enregistré) sur
un mini projet dans tmp_path ; les refus ne lancent aucun process.
"""
from __future__ import annotations

import pytest

import bouzecode.backend.tools.registration  # noqa: F401 — enregistre RunPythonTest
from bouzecode.backend.core.tool_registry import get_tool
from bouzecode.backend.tools.ops.test_runner import run_python_test


@pytest.fixture
def mini_project(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "demo"\nversion = "0"\n')
    (tmp_path / "test_demo.py").write_text(
        "def test_un():\n    assert 1\n\ndef test_deux():\n    assert 2\n")
    return tmp_path


def pytest_imbrique(params: dict) -> str:
    """Appelle RunPythonTest tel que l'agent le voit : l'outil ENREGISTRÉ, ses défauts compris."""
    return get_tool("RunPythonTest").func(params, {})


def _command_line(result: str) -> str:
    return next(line for line in result.splitlines() if line.startswith("$ "))


def test_registered_tool_defaults_to_four_workers(mini_project):
    # `-p no:xdist` : on lit la commande construite sans lancer quatre workers.
    result = pytest_imbrique({"targets": [str(mini_project / "test_demo.py")],
                              "extra_args": ["-p", "no:xdist"], "timeout": 60})
    command = _command_line(result)
    assert " -n 4 " in command
    assert "auto" not in command


@pytest.mark.parametrize("parallel, extra_args", [
    ("auto", None), ("AUTO", None), ("logical", None),
    ("off", ["-n", "auto"]), ("2", ["--numprocesses=auto"]), ("off", ["-nauto"]),
])
def test_unbounded_workers_are_refused_with_the_reason(mini_project, parallel, extra_args):
    result = run_python_test(targets=[str(mini_project / "test_demo.py")],
                             parallel=parallel, extra_args=extra_args)
    assert result.startswith("Error:")
    assert "partagée" in result
    assert "'4'" in result and "'2'" in result and "'off'" in result
    assert "[RunPythonTest] cwd=" not in result, "aucun pytest ne doit être lancé"


def test_non_numeric_parallel_is_refused(mini_project):
    result = run_python_test(targets=[str(mini_project / "test_demo.py")], parallel="many")
    assert result.startswith("Error:") and "'off'" in result


def test_no_target_outside_git_runs_nothing_and_says_how_to_scope(mini_project, monkeypatch):
    """Sans cible, c'est la sélection impactée ; hors dépôt git il n'y a rien à suivre."""
    monkeypatch.chdir(mini_project)
    result = pytest_imbrique({})
    assert result.startswith("impacted:")
    assert "targets=" in result and "full=true" not in result
    assert "[RunPythonTest] cwd=" not in result


def test_full_true_is_refused_to_agents(mini_project, monkeypatch):
    """Décision du 2026-10-14 : la suite complète tourne en nightly sur develop."""
    monkeypatch.chdir(mini_project)
    monkeypatch.delenv("BZ_NIGHTLY", raising=False)
    result = run_python_test(full=True, parallel="off", timeout=60)
    assert result.startswith("Error:") and "nightly sur develop" in result
    assert "lance les tests impactés (sans `targets`)" in result


def test_full_true_runs_the_whole_suite_in_the_nightly(mini_project, monkeypatch):
    monkeypatch.chdir(mini_project)
    monkeypatch.setenv("BZ_NIGHTLY", "1")
    result = run_python_test(full=True, parallel="off", timeout=60)
    assert "2 passed" in result


def test_durations_added_once_and_green_result_is_the_verdict(mini_project):
    """Vert, aucun test ≥ 1 s : le résultat après l'en-tête est la seule ligne de verdict."""
    result = run_python_test(targets=[str(mini_project / "test_demo.py")],
                             parallel="off", timeout=60)
    assert _command_line(result).count("--durations") == 1
    assert "--durations=5" in _command_line(result)
    verdict, chemin = result.split("─" * 60, 1)[1].strip().split("\n")
    assert verdict.startswith("2 passed in "), verdict
    assert chemin.startswith("[full output saved to: "), chemin


def test_full_output_is_always_saved_even_when_green(mini_project):
    result = run_python_test(targets=[str(mini_project / "test_demo.py")],
                             parallel="off", timeout=60)
    chemin = result.rsplit("[full output saved to: ", 1)[1].rstrip("]\n")
    sauvee = open(chemin, encoding="utf-8").read()
    assert "test_demo.py::test_un PASSED" in sauvee


def test_hang_diagnostic_and_no_rerun_by_default(mini_project):
    result = run_python_test(targets=[str(mini_project / "test_demo.py")],
                             parallel="off", timeout=60)
    command = _command_line(result)
    assert "-o faulthandler_timeout=120" in command
    assert "-p no:rerunfailures" in command
    assert "2 passed" in result


def test_caller_faulthandler_and_reruns_are_respected(mini_project):
    result = run_python_test(targets=[str(mini_project / "test_demo.py")], parallel="off",
                             extra_args=["-o", "faulthandler_timeout=30", "--reruns", "2"],
                             timeout=60)
    command = _command_line(result)
    assert command.count("faulthandler_timeout") == 1
    assert "no:rerunfailures" not in command


def test_show_durations_asks_for_fifteen_and_lists_them(mini_project):
    result = pytest_imbrique({"targets": [str(mini_project / "test_demo.py")],
                              "parallel": "off", "show": ["durations"], "timeout": 60})
    assert "--durations=15" in _command_line(result)
    assert "durées :" in result and "2 passed" in result


def test_unknown_show_view_is_refused(mini_project):
    result = run_python_test(targets=[str(mini_project / "test_demo.py")], show=["tout"])
    assert result.startswith("Error:") and "'warnings'" in result
    assert "[RunPythonTest] cwd=" not in result


def test_caller_durations_are_not_doubled(mini_project):
    result = run_python_test(targets=[str(mini_project / "test_demo.py")], parallel="off",
                             extra_args=["--durations=3"], timeout=60)
    command = _command_line(result)
    assert command.count("--durations") == 1
    assert "--durations=3" in command
