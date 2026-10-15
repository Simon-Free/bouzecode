# [desc] Secrets locaux : le .env (identifiants en clair) ne doit jamais redevenir suivi par git, et .gitignore doit l'exclure. [/desc]
"""Le `.env` de la racine a été suivi par git (commit 88cd88d1, retiré par e9eaa8a7) : il
contenait des identifiants en clair. Ce test empêche qu'il soit de nouveau ajouté ; la purge
de l'historique reste une action humaine coordonnée (voir README, section Sécurité)."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[3]


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(RACINE), *args], capture_output=True, text=True)


@pytest.fixture(scope="module", autouse=True)
def _depot_git():
    if _git("rev-parse", "--is-inside-work-tree").stdout.strip() != "true":
        pytest.skip("pas de dépôt git (paquet installé)")


def test_aucun_fichier_env_suivi():
    suivis = [p for p in _git("ls-files").stdout.splitlines()
              if Path(p).name == ".env" or Path(p).name.startswith(".env.")]
    assert suivis == []


def test_env_ignore_par_git():
    assert _git("check-ignore", "-q", ".env").returncode == 0
