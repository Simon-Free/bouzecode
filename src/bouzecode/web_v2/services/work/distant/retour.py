# [desc] Retour d'un agent Rundeck : la branche agent/<ticket> rapatriee est sortie dans un worktree local standard et decrite dans `ticket["worktree"]`, pour que `integrate` suive le chemin local. [/desc]
"""Sans ce module, un ticket execute sur Rundeck n'avait pas de `worktree` : `POST …/integrate`
le refusait en 409 `pas_isole` et la branche `agent/<ticket>` rapatriee se mergeait a la main.

Ici, apres `recuperer` (branche deja importee dans le depot local) : `git worktree add` de la
branche EXISTANTE au meme emplacement que `worktrees.provision` (`WORKTREES_DIR/<depot>/<ticket>`,
sans venv), et le meme meta (`repo_root`, `worktree`, `branch`, `base`). La base est la branche
locale d'ou le travail est parti (le manifeste la note) ; tete detachee -> branche par defaut.

Multi-projets : le depot PRINCIPAL (celui du ticket) devient `ticket["worktree"]` et s'integre par
la route habituelle ; chaque depot secondaire recoit aussi sa branche et son worktree, decrits dans
`ticket["worktrees_secondaires"]` (et dans le digest) pour une integration a la main.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

from .. import tickets, worktrees


def _git(repo_root: str, *arguments: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", repo_root, *arguments], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=180)


def _base(repo_root: str, base: str) -> str:
    if base and base != "HEAD" and _git(repo_root, "rev-parse", "--verify", "--quiet",
                                         f"refs/heads/{base}").returncode == 0:
        return base
    return worktrees.default_branch(repo_root)


def worktree_sur_branche(repo_root: str, ticket_id: str, branche: str, base: str) -> dict:
    """Meta de `worktrees.provision`, sur la branche rapatriee (aucune branche creee)."""
    nom = re.sub(r"[^A-Za-z0-9_-]", "-", ticket_id)
    chemin = worktrees.WORKTREES_DIR / Path(repo_root).name / nom
    worktrees.discard_worktree(repo_root, ticket_id)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    sortie = _git(repo_root, "worktree", "add", str(chemin), branche)
    if sortie.returncode != 0:
        return {"ok": False, "state": "error", "error": sortie.stderr.strip()[-400:], "branch": branche}
    return {"ok": True, "state": "provisioned", "repo_root": repo_root, "worktree": str(chemin),
            "branch": branche, "base": _base(repo_root, base), "venv_ok": False, "origine": "rundeck"}


def preparer(slug: str, ticket: dict, branches: dict) -> dict:
    """Worktree local de chaque branche importee ; pose `worktree` (principal) et
    `worktrees_secondaires` sur le ticket. Rend {slug_projet: meta}."""
    metas = {projet: worktree_sur_branche(info["depot"], ticket["id"], info["branche"], info.get("base", ""))
             for projet, info in branches.items() if info.get("ok") and info.get("depot")}
    principal = slug if slug in metas else next(iter(metas), "")
    secondaires = [{"projet": p, **m} for p, m in metas.items() if p != principal]
    champs = {}
    if principal and metas[principal].get("ok"):
        champs["worktree"] = metas[principal]
    if secondaires:
        champs["worktrees_secondaires"] = secondaires
    if champs:
        tickets.poser(slug, ticket, **champs)
    return metas
