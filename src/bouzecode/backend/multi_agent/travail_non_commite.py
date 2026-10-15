# [desc] Avertit parent et enfant web quand le worktree du parent a des fichiers non commités, que l'enfant ne trouvera pas dans sa branche de départ. [/desc]
"""Le sous-agent web part de la DERNIÈRE VERSION COMMITÉE de la branche du parent."""
from __future__ import annotations

import os


#  Dossiers de travail jamais pertinents pour un enfant (et qu'on ne veut surtout pas lister).
_BRUIT_WORKTREE = (".venv/", "venv/", "node_modules/", "__pycache__/", ".cache/",
                   ".pytest_cache/", ".mypy_cache/", ".ruff_cache/")


def _travail_non_commite(racine: str) -> list[str]:
    """Fichiers modifiés ou nouveaux du worktree du parent, hors dossiers de bruit."""
    import subprocess
    try:
        out = subprocess.run(["git", "status", "--porcelain", "--untracked-files=normal"],
                             cwd=racine, capture_output=True, text=True, timeout=30).stdout
    except Exception:  # git absent ou dossier disparu : rien à signaler
        return []
    fichiers = [ligne[3:].strip() for ligne in out.splitlines() if len(ligne) > 3]
    return [f for f in fichiers if not f.startswith(_BRUIT_WORKTREE) and not f.endswith(".pyc")]


def _avertir_travail_non_commite(params: dict) -> str:
    """Le sous-agent part de la DERNIÈRE VERSION COMMITÉE de la branche du parent : il ne voit
    pas les fichiers que le parent n'a pas commités (vu en réel : un SPEC.md écrit puis délégué,
    introuvable pour l'enfant). On ne commite PAS à la place du parent (on embarquerait des
    fichiers temporaires) : on prévient les deux. Renvoie l'avertissement pour le parent."""
    racine = os.environ.get("BOUZECODE_WORKTREE_ROOT", "")
    if not racine or not os.path.isdir(racine):
        return ""
    fichiers = _travail_non_commite(racine)
    if not fichiers:
        return ""
    liste = ", ".join(fichiers[:10]) + (f" (+{len(fichiers) - 10})" if len(fichiers) > 10 else "")
    params["prompt"] = (
        f"{params['prompt']}\n\n[Note de l'outil] Ton agent parent avait des fichiers NON "
        f"commités au moment de te déléguer ({liste}) : ils ne sont pas dans ta branche de "
        f"départ. Si tu en as besoin, lis-les (lecture seule) dans son worktree {racine}, ou "
        f"demande-lui de les commiter.")
    return (f"⚠️ Ton worktree {racine} a des fichiers non commités ({liste}) : ton sous-agent ne "
            f"les a PAS dans sa branche (il a reçu leur chemin pour les lire). Commite-les si "
            f"d'autres délégations en dépendent, et AVANT qu'il n'intègre dans ta branche "
            f"(sinon sa fusion sera refusée).")
