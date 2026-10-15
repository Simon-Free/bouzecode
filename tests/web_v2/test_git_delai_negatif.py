"""Un délai git « dépassé de -3994 s » n'est pas un vrai dépassement.

Constat (session 3db4403a, poste Windows) : `Environment(action='integrate')` a échoué sur
« Command '['git', ..., 'grep', '-lE', ...]' timed out after -3994.047 seconds ». Un délai
restant NÉGATIF de plus d'une heure signifie que l'horloge a sauté pendant l'appel (mise en
veille du portable : le temps monotone de Windows la compte) — le process git, lui, avait
terminé. On relance une fois ; un vrai dépassement reste signalé avec le délai configuré.
"""
import subprocess

import pytest

from bouzecode.web_v2.services.work import worktrees


def test_un_saut_dhorloge_est_relance_une_fois(monkeypatch):
    appels = []

    def _run(cmd, **kwargs):
        appels.append(cmd)
        if len(appels) == 1:
            raise subprocess.TimeoutExpired(cmd, -3994.047)
        return subprocess.CompletedProcess(cmd, 0, "ok\n", "")

    monkeypatch.setattr(worktrees.subprocess, "run", _run)
    assert worktrees._out("/depot", "grep", "-lE", "^<<<<<<< ") == "ok"
    assert len(appels) == 2


def test_un_vrai_depassement_annonce_le_delai_configure(monkeypatch):
    def _run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, -12.0)

    monkeypatch.setattr(worktrees.subprocess, "run", _run)
    with pytest.raises(subprocess.TimeoutExpired) as exc:
        worktrees._run("/depot", "status")
    assert exc.value.timeout == 120


def test_environment_traduit_un_delai_git_depasse(monkeypatch):
    from bouzecode.backend.tools import environment

    def _lent(config):
        raise subprocess.TimeoutExpired(["git", "-C", "/depot", "merge"], 120)

    monkeypatch.setitem(environment._HANDLERS, "status", _lent)
    out = environment._environment({"action": "status"}, {})
    assert "120" in out and "git" in out
    assert "git status" in out  # quoi vérifier avant de relancer
