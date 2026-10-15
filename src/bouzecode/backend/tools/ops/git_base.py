# [desc] Git pour RunPythonTest : merge-base avec develop (sinon master), fichiers changés par la branche (+ non commités + non suivis), nom du dépôt, worktree jetable d'un commit. [/desc]
"""Lecture seule du dépôt, sauf `worktree_jetable` qui crée puis RETIRE un worktree détaché :
la branche de base n'est jamais touchée."""
from __future__ import annotations

import contextlib
import shutil
import subprocess
import tempfile
from pathlib import Path

from ...testd.common import sans_fenetre

BRANCHES_DE_BASE = ("develop", "master")


def git(racine: Path, *args: str, verifier: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(racine), capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=120, check=verifier,
                          **sans_fenetre())


def base_de_la_branche(racine: Path) -> tuple[str, str]:
    """(nom, sha) du merge-base de HEAD avec develop, sinon master ; ("", "") sans base."""
    for nom in BRANCHES_DE_BASE:
        sortie = git(racine, "merge-base", "HEAD", nom)
        if sortie.returncode == 0 and sortie.stdout.strip():
            return nom, sortie.stdout.strip()
    return "", ""


def fichiers_changes(racine: Path, sha_base: str) -> list[str]:
    """Chemins relatifs à `racine` (posix) changés depuis `sha_base`, non commités ou non suivis."""
    commandes = [["diff", "--name-only", "--relative", "HEAD"],
                 ["ls-files", "--others", "--exclude-standard"]]
    if sha_base:
        commandes.insert(0, ["diff", "--name-only", "--relative", f"{sha_base}...HEAD"])
    changes: set[str] = set()
    for commande in commandes:
        sortie = git(racine, *commande)
        if sortie.returncode == 0:
            changes.update(l.strip().replace("\\", "/") for l in sortie.stdout.splitlines() if l.strip())
    return sorted(changes)


def racine_git(racine: Path) -> Path:
    return Path(git(racine, "rev-parse", "--show-toplevel", verifier=True).stdout.strip())


def nom_du_depot(racine: Path) -> str:
    """Nom du dépôt PRINCIPAL (le même depuis tous ses worktrees)."""
    commun = git(racine, "rev-parse", "--path-format=absolute", "--git-common-dir",
                 verifier=True).stdout.strip()
    return Path(commun).parent.name


@contextlib.contextmanager
def worktree_jetable(racine: Path, sha: str):
    """Worktree détaché de `sha`, retiré en sortie (même sur exception)."""
    dossier = Path(tempfile.mkdtemp(prefix="bz_base_"))
    git(racine, "worktree", "add", "--detach", "--force", str(dossier), sha, verifier=True)
    try:
        yield dossier
    finally:
        git(racine, "worktree", "remove", "--force", str(dossier))
        shutil.rmtree(dossier, ignore_errors=True)
        git(racine, "worktree", "prune")
