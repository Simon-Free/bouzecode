# [desc] Un path devenu dépôt git après un premier appel est reconnu au suivant (pas de cache négatif). [/desc]
"""Bug B3 : un worktree interrogé pendant son provisioning n'est pas encore un dépôt
git ; l'échec était mémorisé à vie et l'UI affichait dépôt + branche vides jusqu'au
redémarrage du serveur."""
import subprocess

from bouzecode.web_v2.services.work import repos


def test_worktree_provisionne_apres_un_premier_appel_est_reconnu(tmp_path):
    """Le dépôt d'un worktree créé après un premier affichage apparaît au poll suivant."""
    worktree = tmp_path / "wt_f7"

    # 1er appel : le ticket est encore en provisioning, le dossier n'existe pas.
    assert repos.repo_key(str(worktree)) is None
    assert repos.repo_name(str(worktree), None) == "wt_f7"

    # Le worktree est provisionné.
    subprocess.run(["git", "init", str(worktree)], check=True, capture_output=True)

    # 2e appel : le dépôt est identifié (avant le correctif : toujours None).
    key = repos.repo_key(str(worktree))
    assert key is not None
    assert repos.repo_name(str(worktree), key) == "wt_f7"
