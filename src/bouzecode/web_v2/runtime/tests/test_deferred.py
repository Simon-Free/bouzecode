"""Tests for the deferred-checks drain layer (web/deferred.py + DeferredChecks)."""
from __future__ import annotations

import sys

import pytest

from bouzecode.web_v2.runtime import deferred as web_deferred
from bouzecode.web_v2.runtime.runner import agent_reprise
from bouzecode.backend.tools.interaction import DeferredChecks


@pytest.mark.skipif(sys.platform != "win32", reason="PowerShell shell path is Windows-only")
def test_run_deferred_check_uses_powershell_not_cmd(tmp_path):
    """A deferred command authored in PowerShell must run in PowerShell, not cmd.exe.

    Regression: `_maybe_drain_deferred` ran commands via `subprocess.run(shell=True)`,
    i.e. cmd.exe on Windows, which fails instantly on `$env:` / `;`-chained PowerShell
    syntax — so a queued Azure deploy silently never executed. `_run_deferred_check`
    routes through the canonical PowerShell wrapper instead."""
    result = agent_reprise._run_deferred_check(
        '$env:DEFERRED_PROBE = "ok"; Write-Output $env:DEFERRED_PROBE', str(tmp_path), 60)
    assert result.returncode == 0, result.stderr
    assert "ok" in result.stdout


@pytest.mark.skipif(sys.platform != "win32", reason="PowerShell shell path is Windows-only")
def test_lancer_une_ne_transmet_pas_pythonhome(tmp_path, monkeypatch):
    """Le PYTHONHOME que uv laisse fuir dans bouzecode ne doit pas atteindre la vérification.

    Régression : `lancer_une` héritait de l'env du process ; un venv 3.13 lancé avec le
    PYTHONHOME de la cpython-3.12 de uv mourait sur `AssertionError: SRE module mismatch`."""
    monkeypatch.setenv("PYTHONHOME", r"C:\fuite\cpython-3.12")
    result = web_deferred.lancer_une(
        'Write-Output "[$env:PYTHONHOME]"', str(tmp_path), 60)
    assert result.returncode == 0, result.stderr
    assert "[]" in result.stdout, result.stdout


def test_deferred_save_load_delete_round_trip(tmp_path):
    session = tmp_path / "agent-session.json"
    checks = [
        {"command": "pytest -q", "timeout": 600},
        {"command": "ruff check .", "timeout": 120},
    ]
    exc = DeferredChecks(answer="All green, see report.", checks=checks)

    web_deferred.save(session, exc)

    expected = web_deferred.deferred_path(session)
    assert expected.exists()
    assert web_deferred.exists(session)

    loaded = web_deferred.load(session)
    assert loaded == {"answer": "All green, see report.", "checks": checks}

    web_deferred.delete(session)
    assert not expected.exists()
    assert not web_deferred.exists(session)
    assert web_deferred.load(session) is None


def test_deferred_checks_carries_answer_and_queue():
    queue = [{"command": "echo hi", "timeout": 30}]
    exc = DeferredChecks(answer="done", checks=list(queue))
    assert exc.answer == "done"
    assert exc.checks == queue
    assert "1 command" in str(exc)


def test_deferred_checks_empty_queue_defaults():
    exc = DeferredChecks(answer="done")
    assert exc.answer == "done"
    assert exc.checks == []
