# [desc] Ne jamais perdre un commit d'agent : reprendre sa branche, ou la taguer avant de la supprimer. [/desc]
"""Relancer un ticket ne doit pas coûter le travail déjà commité sur sa branche.

Le retry isolé (`dispatch.reisolate`) purgeait le bac à sable avec `git branch -D
agent/<id>` avant de re-provisionner : les commits que la branche portait disparaissaient
avec elle, sans trace ni message (le reflog de la branche part avec la branche). Cas vécu
du 28/07 sur quatre tickets, dont une sauvegarde posée à la main.

Deux gestes, dans cet ordre :
  1. REPRENDRE — si la branche porte du travail absent de la base, on la re-sort telle
     quelle dans un worktree neuf : la relance CONTINUE le travail au lieu de le refaire ;
  2. SAUVEGARDER — si elle doit malgré tout disparaître, son tip est d'abord tagué
     `rescue/...`. Une suppression n'est autorisée qu'une fois la sauvegarde acquise.

Le meta renvoyé est celui de `worktrees.provision` (mêmes clés) SANS `in_place` : la
branche reste une branche d'agent, à merger normalement dans la base à l'intégration."""
from __future__ import annotations

import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any


def _run(cwd: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", cwd, *args], capture_output=True,
                          text=True, encoding="utf-8", errors="replace", timeout=120)


def worktree_name(ticket_id: str) -> str:
    """Nom de dossier/branche dérivé de l'id du ticket (même règle que `worktrees`)."""
    return re.sub(r"[^A-Za-z0-9_-]", "-", ticket_id)


def agent_branch(ticket_id: str) -> str:
    return f"agent/{worktree_name(ticket_id)}"


def branch_tip(repo_root: str, branch: str) -> str:
    """SHA du tip de `branch`, "" si elle n'existe pas."""
    res = _run(repo_root, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}")
    return res.stdout.strip() if res.returncode == 0 else ""


def carries_work(repo_root: str, branch: str, base: str) -> bool:
    """`branch` porte-t-elle des commits ABSENTS de `base` ?

    Une comparaison IMPOSSIBLE (base inconnue, branche absente de la base) répond OUI :
    devant l'inconnu on préserve, jamais l'inverse — c'est tout l'objet de ce module."""
    if not branch_tip(repo_root, branch):
        return False
    res = _run(repo_root, "rev-list", "--count", f"{base}..{branch}")
    if res.returncode != 0:
        return True
    return res.stdout.strip() not in ("", "0")


def drop_branch(repo_root: str, branch: str, base: str) -> dict[str, Any]:
    """Supprime `branch` APRÈS avoir mis son travail en sûreté.

    Renvoie `{deleted, rescue_tag, tip, error}`. Quand la branche porte du travail et que
    le tag de sauvegarde ne peut PAS être posé, la branche est CONSERVÉE et l'erreur est
    remontée : mieux vaut une re-provision qui échoue qu'un commit effacé."""
    tip = branch_tip(repo_root, branch)
    if not tip:
        return {"deleted": False, "rescue_tag": "", "tip": "", "error": ""}
    rescue_tag = ""
    if carries_work(repo_root, branch, base):
        rescue_tag = (f"rescue/{branch.replace('/', '-')}-"
                      f"{datetime.now().strftime('%Y%m%d-%H%M%S')}")
        tagged = _run(repo_root, "tag", rescue_tag, tip)
        if tagged.returncode != 0:
            return {"deleted": False, "rescue_tag": "", "tip": tip,
                    "error": f"sauvegarde impossible ({tagged.stderr.strip()}) : "
                             f"la branche {branch} est conservée telle quelle"}
    deleted = _run(repo_root, "branch", "-D", branch)
    return {"deleted": deleted.returncode == 0, "rescue_tag": rescue_tag, "tip": tip,
            "error": "" if deleted.returncode == 0 else deleted.stderr.strip()}


def resume_on_branch(repo_root: str, ticket_id: str, branch: str, base: str,
                     worktrees_dir: Path) -> dict[str, Any]:
    """Re-sort la branche EXISTANTE (avec ses commits) dans un worktree neuf.

    `{}` quand il n'y a rien à reprendre (branche absente ou sans travail propre) ou que
    le checkout échoue — l'appelant retombe alors sur la re-provision, qui reste protégée
    par `drop_branch`."""
    if not carries_work(repo_root, branch, base):
        return {}
    worktree = worktrees_dir / Path(repo_root).name / worktree_name(ticket_id)
    worktree.parent.mkdir(parents=True, exist_ok=True)
    if _run(repo_root, "worktree", "add", str(worktree), branch).returncode != 0:
        return {}
    return {"ok": True, "state": "provisioned", "repo_root": repo_root,
            "worktree": str(worktree), "branch": branch, "base": base,
            "venv_ok": False, "resumed": True}
