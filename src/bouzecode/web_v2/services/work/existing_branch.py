# [desc] Provisionner un worktree SUR une branche existante : honoré, ou refusé en nommant l'occupant. [/desc]
"""« Travaille sur CETTE branche » — la demande que `resume_branch` ne sait pas exprimer.

`resume_branch` veut dire « pars DE cette branche » : `worktrees.provision` fait
`git worktree add -b agent/<ticket> <base>`, donc l'agent atterrit toujours sur une branche
NEUVE. Un manager qui écrivait « ta branche de travail = agent/XXX » voyait sa demande
acceptée puis silencieusement remplacée : le travail était juste, rendu `VERDICT: OK`, et
la branche visée restait intacte — personne ne le signalait.

Ce module provisionne SUR la branche demandée (`git worktree add <path> <branche>`, sans
`-b`), et refuse BRUYAMMENT les deux seuls cas où c'est impossible : branche inexistante, ou
branche déjà sortie dans un autre worktree (git le refuse — cf. `occupant`). Jamais de repli
silencieux sur une branche neuve.

`base` du meta = le SHA du tip AU MOMENT du provisioning : c'est ce qui rend `harvest` capable
de montrer exactement ce que l'agent a ajouté (un `base` égal à la branche donnerait un diff
vide, donc une livraison invisible). `in_place` marque que la livraison est DÉJÀ sur la
branche demandée — il n'y a rien à merger, cf. `worktrees.integrate`."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any


def _run(cwd: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", cwd, *args], capture_output=True,
                          text=True, encoding="utf-8", errors="replace", timeout=120)


def exists(repo_root: str, branch: str) -> bool:
    """La branche locale existe-t-elle dans ce dépôt ?"""
    return _run(repo_root, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}").returncode == 0


def occupant(repo_root: str, branch: str) -> str:
    """Chemin du worktree qui a DÉJÀ `branch` sortie, "" si elle est libre.

    git refuse `worktree add <path> <branch>` quand la branche est sortie ailleurs
    (« fatal: 'X' is already checked out at ... »). On le constate AVANT d'essayer, pour
    pouvoir nommer l'occupant dans un message actionnable plutôt que relayer un fatal brut.
    `git worktree list --porcelain` émet un bloc par worktree : `worktree <path>` puis, si la
    HEAD est attachée, `branch refs/heads/<nom>`."""
    listing = _run(repo_root, "worktree", "list", "--porcelain")
    if listing.returncode != 0:
        return ""
    current = ""
    for line in listing.stdout.splitlines():
        if line.startswith("worktree "):
            current = line[len("worktree "):].strip()
        elif line.strip() == f"branch refs/heads/{branch}":
            return current
    return ""


def unavailable_reason(repo_root: str, branch: str) -> str:
    """Pourquoi cette branche NE PEUT PAS être donnée à un agent — "" si elle est disponible.

    Appelé en pré-vol par `dispatch` : la demande est refusée AVANT que le ticket existe, si
    bien que le manager reçoit une erreur d'outil immédiate et actionnable au lieu d'un agent
    lancé sur autre chose."""
    if not exists(repo_root, branch):
        return (f"branche '{branch}' introuvable dans {repo_root} — aucun agent lancé. "
                f"Vérifie le nom, ou laisse `work_branch` vide pour une branche neuve.")
    busy = occupant(repo_root, branch)
    if busy:
        return (f"branche '{branch}' déjà sortie dans le worktree {busy} — aucun agent lancé. "
                f"Deux worktrees ne peuvent pas avoir la même branche. Attends la fin de "
                f"l'agent qui l'occupe, ou fais-le livrer, ou lance celui-ci sans "
                f"`work_branch` (branche neuve).")
    return ""


def provision_on(repo_root: str, ticket_id: str, branch: str,
                 worktrees_dir: Path) -> dict[str, Any]:
    """Sort `branch` (EXISTANTE) dans le worktree du ticket. Aucune branche neuve n'est créée.

    Renvoie le même meta que `worktrees.provision`, plus `in_place: True`. En cas d'échec,
    `{"ok": False, "error": ...}` avec un message qui nomme l'occupant — l'appelant doit
    remonter cette erreur, jamais se rabattre sur autre chose."""
    reason = unavailable_reason(repo_root, branch)
    if reason:
        return {"ok": False, "error": reason, "state": "error"}
    name = re.sub(r"[^A-Za-z0-9_-]", "-", ticket_id)
    worktree = worktrees_dir / Path(repo_root).name / name
    worktree.parent.mkdir(parents=True, exist_ok=True)
    tip = _run(repo_root, "rev-parse", branch).stdout.strip()
    res = _run(repo_root, "worktree", "add", str(worktree), branch)
    if res.returncode != 0:
        return {"ok": False, "error": res.stderr.strip(), "state": "error"}
    return {"ok": True, "state": "provisioned", "repo_root": repo_root,
            "worktree": str(worktree), "branch": branch, "base": tip,
            "in_place": True, "venv_ok": False}
