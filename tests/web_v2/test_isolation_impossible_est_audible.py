# [desc] Une isolation EXIGÉE mais impossible (projet non-git) ne dégrade jamais en silence. [/desc]
"""Un worktree exigé et non obtenu doit s'entendre.

`resolve_isolation` rend `shared` quand le projet n'est pas un dépôt git — normal, aucun
worktree n'y est possible. Mais quand le worktree était une EXIGENCE (ticket éphémère,
reprise de branche, branche de travail), cette dégradation change ce que l'agent va faire :
il écrit dans l'arbre principal, sur la branche courante, au lieu de la branche attendue.
Livrer ailleurs que là où on l'attend est le défaut le plus coûteux de la chaîne, parce
qu'il ne se voit pas.

Le garde-fou écrit dans `_provision_worktree` pour ce cas (`raise` sur `work_branch`) est
INATTEIGNABLE : `resolve_isolation` a déjà rendu `shared`, donc `_launch` ne provisionne
rien et ne l'appelle jamais. L'intention de refuser existait dans le code et ne s'exécutait
pas — on la rend au moins AUDIBLE ici, sans changer la décision d'isolation.
"""
from __future__ import annotations

from bouzecode.web_v2.services.work.isolation import SHARED, WORKTREE, resolve_isolation


def test_projet_non_git_sans_exigence_degrade_sans_bruit(tmp_path):
    """Personne n'a demandé de worktree : `shared` est le bon mode et ne mérite aucun
    commentaire. Un garde qui parle pour rien finit désactivé."""
    mode, raison, commentaire = resolve_isolation(str(tmp_path), SHARED, needs_worktree=False)

    assert mode == SHARED
    assert "pas un dépôt git" in raison
    assert commentaire == ""


def test_projet_non_git_avec_exigence_le_dit(tmp_path):
    """Le worktree était EXIGÉ (éphémère / reprise / branche de travail) et n'a pas été
    obtenu : le commentaire doit nommer la conséquence, pas seulement la cause."""
    mode, raison, commentaire = resolve_isolation(str(tmp_path), SHARED, needs_worktree=True)

    assert mode == SHARED, "aucun worktree n'est possible hors dépôt git"
    assert "pas un dépôt git" in raison
    assert commentaire, "dégradation d'une isolation EXIGÉE rendue en silence"
    assert "ARBRE PRINCIPAL" in commentaire, "le commentaire doit dire où l'agent va écrire"
    assert str(tmp_path) in commentaire, "le commentaire doit nommer le projet en cause"


def test_depot_git_normal_n_est_pas_signale(tmp_path):
    """Preuve de non-hurlement : un vrai dépôt obtient son worktree, sans commentaire."""
    import subprocess

    subprocess.run(["git", "init", "-q", str(tmp_path)], capture_output=True)

    mode, _raison, commentaire = resolve_isolation(str(tmp_path), SHARED, needs_worktree=True)

    assert mode == WORKTREE
    assert commentaire == ""
