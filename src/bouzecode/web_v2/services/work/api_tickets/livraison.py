# [desc] Ce que la branche d'un ticket porte : `delivery {head, commits_ahead, code_files_ahead, dirty, checked_at}` (ancestralité du TRAVAIL, fichiers de méta ignorés), son diff, et la récolte explicite. [/desc]
"""Spec §3.1 `delivery`, §5.4. Calculé en fin de run, au tick du watchdog et sur demande
(`POST …/delivery/refresh`), JAMAIS à la lecture.

« Rien à intégrer » se décide sur les FICHIERS DE CODE en avance sur la base (diff
`base...branche`, depuis leur ancêtre commun), pas sur la seule avance en commits : un résidu
`uv.lock` / `SYMBOLS.md` / `AGENTS.md` posé après une intégration n'est pas du travail. La liste
des fichiers de méta est réglable (`BOUZECODE_FICHIERS_META`, noms séparés par des virgules).
Un worktree disparu ne change rien : on lit la BRANCHE, qui existe toujours."""
from __future__ import annotations

import os
import subprocess
from pathlib import PurePosixPath

from bouzecode.web_v2.services.horodatage import maintenant_iso

from .. import branch_rescue, tickets, worktrees
from .refus import Refus

FICHIERS_META = ("uv.lock", "SYMBOLS.md", "AGENTS.md")
_GIT_TIMEOUT_S = 20


def fichiers_meta() -> set[str]:
    reglage = os.environ.get("BOUZECODE_FICHIERS_META", "")
    return {nom.strip() for nom in reglage.split(",") if nom.strip()} or set(FICHIERS_META)


def est_du_code(chemin: str, meta: set[str] | None = None) -> bool:
    return PurePosixPath(chemin.replace("\\", "/")).name not in (meta or fichiers_meta())


def _git(racine: str, *args: str) -> str:
    try:
        res = worktrees._run(racine, *args, timeout=_GIT_TIMEOUT_S)
    except subprocess.TimeoutExpired as lent:
        raise Refus("git_trop_lent", f"git ne répond pas à temps : {lent}", 504) from lent
    return (res.stdout or "").strip() if res.returncode == 0 else ""


def reperes(ticket: dict) -> dict | None:
    """(racine, base, branche) d'un ticket isolé ; None pour un ticket `shared`."""
    meta = ticket.get("worktree") if isinstance(ticket.get("worktree"), dict) else {}
    racine, base = meta.get("repo_root") or "", meta.get("base") or ""
    if not (racine and base):
        return None
    return {"racine": racine, "base": base,
            "branche": meta.get("branch") or branch_rescue.agent_branch(str(ticket["id"])),
            "worktree": meta}


def calculer(ticket: dict) -> dict | None:
    """Le constat de livraison (lecture git seule) ; None pour un ticket non isolé."""
    rep = reperes(ticket)
    if rep is None:
        return None
    racine, plage = rep["racine"], f"{rep['base']}...{rep['branche']}"
    tete = _git(racine, "rev-parse", "--verify", "--quiet", rep["branche"])
    avance = _git(racine, "rev-list", "--count", f"{rep['base']}..{rep['branche']}") if tete else ""
    fichiers = _git(racine, "diff", "--name-only", plage).splitlines() if tete else []
    sales = worktrees.dirty_files(rep["worktree"]) if worktrees.dir_exists(rep["worktree"]) else []
    meta = fichiers_meta()
    return {"head": tete, "commits_ahead": int(avance) if avance.isdigit() else 0,
            "code_files_ahead": sum(1 for f in fichiers if est_du_code(f, meta)),
            "dirty": bool(sales), "dirty_code_files": sum(1 for f in sales if est_du_code(f, meta)),
            "checked_at": maintenant_iso()}


def rafraichir(slug: str, ticket: dict) -> dict | None:
    """Recalcule et PERSISTE `delivery` (geste explicite ou fin de run)."""
    constat = calculer(ticket)
    if constat is not None:
        tickets.poser(slug, ticket, delivery=constat)
    return constat


def travail_a_integrer(constat: dict | None) -> bool:
    return bool(constat) and (constat["code_files_ahead"] > 0 or constat["dirty_code_files"] > 0)


def diff(ticket: dict) -> dict:
    """{branch, base, commits, files} de la branche du ticket contre sa base (lecture)."""
    rep = reperes(ticket)
    if rep is None:
        return {"branch": "", "base": "", "commits": [], "files": [], "isolated": False}
    racine, plage = rep["racine"], f"{rep['base']}...{rep['branche']}"
    commits = [{"sha": ligne[:40], "subject": ligne[41:]} for ligne in _git(
        racine, "log", "--format=%H %s", "-n", "50", f"{rep['base']}..{rep['branche']}").splitlines()
        if ligne]
    fichiers = [{"status": ligne.split("\t", 1)[0], "path": ligne.split("\t")[-1],
                 "code": est_du_code(ligne.split("\t")[-1])}
                for ligne in _git(racine, "diff", "--name-status", plage).splitlines() if ligne]
    return {"branch": rep["branche"], "base": rep["base"], "commits": commits, "files": fichiers,
            "isolated": True, "mr_links": list(ticket.get("mr_links") or [])}


def recolter(slug: str, ticket: dict) -> dict:
    """`POST …/harvest` : commite le travail non commité du worktree. 409 `run_vivant` si un
    agent tourne, `pas_isole` pour un ticket `shared`, `conflit_en_cours` si un merge est
    inachevé dans le worktree."""
    from .. import delivery, nettoyage
    vivant = nettoyage.run_vivant(ticket)
    if vivant:
        raise Refus("run_vivant", f"un run est vivant ({vivant}) : arrête-le avant de récolter",
                    409, agent_id=vivant, state=ticket.get("state"))
    rep = reperes(ticket)
    if rep is None:
        raise Refus("pas_isole", "ticket non isolé : il n'a pas de worktree à récolter", 409)
    if not worktrees.dir_exists(rep["worktree"]):
        return {"ok": True, "commit": None, "dirty": [], "worktree": "absent"}
    bloque = worktrees.blocage_recolte(rep["worktree"]["worktree"])
    if bloque is not None:
        raise Refus("conflit_en_cours", bloque["message"], 409, files=bloque["fichiers"])
    recolte = worktrees.harvest(rep["worktree"], ticket.get("title", ""))
    delivery.noter_recolte(slug, ticket, recolte)
    rafraichir(slug, ticket)
    return {"ok": True, "commit": recolte.get("head") if recolte.get("committed") else None,
            "dirty": list(recolte.get("dirty") or [])}
