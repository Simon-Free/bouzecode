"""Combien de commits la branche d'un ticket porte-t-elle, qui ne sont pas dans sa base ?

C'est la mesure de l'ACTE RESTANT : des commits non intégrés = un geste à faire (intégrer,
demander une correction, abandonner). Sans eux, un ticket fini n'a rien à relire.

SEUL endroit git du lot Bureau L2, et il ne tourne QU'AU TICK du watchdog : `GET /api/board`
a un budget de 300 ms p95 et interdit git dans son chemin de lecture. Le résultat est mémorisé
dans le ticket (`delivery`, spec §3.1) ; `_status.remaining_of()` le relit sans
jamais lancer un process.

Devant une erreur git (dépôt absent, base inconnue, branche disparue) le compte est 0 : une
décision FABRIQUÉE sur une panne polluerait le Bureau, alors qu'un 0 se corrige au tick suivant.
"""
from __future__ import annotations

import logging
import subprocess
from typing import Any, Iterable

from . import branch_rescue
from .unmerged_memoire import (  # noqa: F401 — ré-export : `une_passe`, mémoires des tests
    _codes, _comptes, dans_les_refs, memorise, refs_de_la_passe, une_passe,
)

_log = logging.getLogger(__name__)


def _lire_refs(repo_root: str) -> dict[str, str] | None:
    try:
        res = _run(repo_root, "for-each-ref", "--format=%(objectname) %(refname)")
    except (OSError, subprocess.SubprocessError) as exc:
        _log.warning("unmerged: refs illisibles dans %s : %s", repo_root, exc)
        return None
    if res.returncode != 0:
        return None
    refs: dict[str, str] = {}
    for ligne in (res.stdout or "").splitlines():
        sha, _, nom = ligne.strip().partition(" ")
        if sha and nom:
            refs[nom] = sha
    return refs


def _refs_de_la_passe(repo_root: str) -> dict[str, str] | None:
    """Refs du dépôt lues une fois pour la passe en cours (`unmerged_memoire`) ; None hors passe."""
    return refs_de_la_passe(repo_root, _lire_refs)


def _run(cwd: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", cwd, *args], capture_output=True,
                          text=True, encoding="utf-8", errors="replace", timeout=60)


def _count(repo_root: str, base: str, branch: str) -> int:
    """Commits de `branch` absents de `base`. 0 dès que la comparaison est impossible."""
    try:
        res = _run(repo_root, "rev-list", "--count", f"{base}..{branch}")
    except (OSError, subprocess.SubprocessError) as exc:
        _log.warning("unmerged: rev-list impossible dans %s (%s..%s) : %s",
                     repo_root, base, branch, exc)
        return 0
    if res.returncode != 0:
        _log.warning("unmerged: rev-list %s..%s a échoué dans %s : %s",
                     base, branch, repo_root, (res.stderr or "").strip()[:200])
        return 0
    out = (res.stdout or "").strip()
    return int(out) if out.isdigit() else 0


def _tip(repo_root: str, branch: str) -> str:
    refs = _refs_de_la_passe(repo_root)
    if refs is not None:
        return refs.get(f"refs/heads/{branch}", "")
    try:
        return branch_rescue.branch_tip(repo_root, branch)
    except (OSError, subprocess.SubprocessError) as exc:
        _log.warning("unmerged: tip de %s illisible dans %s : %s", branch, repo_root, exc)
        return ""


def _rev(repo_root: str, ref: str) -> str:
    """SHA de `ref`, "" si elle est inconnue. Sans préfixe `refs/heads/` : une base peut être
    une branche locale (`develop`), une remote-tracking (`origin/develop`) ou un SHA."""
    refs = _refs_de_la_passe(repo_root)
    if refs is not None:
        connu = dans_les_refs(refs, ref)
        if connu is not None:
            return connu
    try:
        res = _run(repo_root, "rev-parse", "--verify", "--quiet", ref)
    except (OSError, subprocess.SubprocessError) as exc:
        _log.warning("unmerged: rev-parse %s impossible dans %s : %s", ref, repo_root, exc)
        return ""
    return (res.stdout or "").strip() if res.returncode == 0 else ""


def _constat(ticket: dict, tete: str = "", commits: int = 0, code: int = 0,
             marker: str = "") -> None:
    """Pose `ticket["delivery"]` (spec §3.1) ; l'état SALE du worktree, lu seulement en fin de
    run ou sur refresh (jamais au tick), est conservé tel quel."""
    from bouzecode.web_v2.services.horodatage import maintenant_iso
    precedent = ticket.get("delivery") if isinstance(ticket.get("delivery"), dict) else {}
    ticket["delivery"] = {"head": tete, "commits_ahead": commits, "code_files_ahead": code,
                          "dirty": bool(precedent.get("dirty")),
                          "dirty_code_files": int(precedent.get("dirty_code_files") or 0),
                          "checked_at": maintenant_iso(),
                          "marker": marker}
    ticket.pop("unmerged_commits", None)
    ticket.pop("unmerged_tip", None)


def marker_de(ticket: dict) -> str:
    return str((ticket.get("delivery") or {}).get("marker") or "") if isinstance(
        ticket.get("delivery"), dict) else ""


def scan_ticket(ticket: dict) -> str:
    """Met à jour `delivery` (commits et FICHIERS DE CODE en avance) sur UN ticket. Rend
    "scanned" | "skipped".

    "skipped" = aucun git lancé : rien à intégrer par construction (pas de worktree, déjà
    intégré, branche absente) ou comparaison inchangée depuis le dernier tick.

    Le repère mémorisé est le COUPLE `"<rev base>..<rev branche>"`, pas le seul tip de la
    branche : un merge fait avancer la BASE sans toucher la branche agent, et une mémoïsation
    sur le tip seul laisserait donc une livraison déjà intégrée éternellement « à décider ».
    """
    meta = ticket.get("worktree") or {}
    repo_root = meta.get("repo_root") or ""
    base = meta.get("base") or ""
    branch = meta.get("branch") or branch_rescue.agent_branch(str(ticket.get("id") or ""))

    from .etat_ticket import integre
    if not repo_root or not base or integre(ticket):
        _constat(ticket)
        return "skipped"

    tip = _tip(repo_root, branch)
    if not tip:
        _constat(ticket)
        return "skipped"
    base_rev = _rev(repo_root, base)
    marker = f"{base_rev}..{tip}"
    if marker == marker_de(ticket):
        return "skipped"
    commits = _count_memorise(repo_root, base, branch, base_rev, tip)
    _constat(ticket, tip, commits, _code_memorise(repo_root, base_rev or base, tip)
             if commits else 0, marker)
    return "scanned"


def _count_memorise(repo_root: str, base: str, branch: str, base_rev: str, tip: str) -> int:
    """`_count` mémorisé par (dépôt, sha de base, sha du tip) — immuable. Base irrésolue :
    pas de mémoire (le compte vaut 0 et se corrige au tick suivant)."""
    if not base_rev:
        return _count(repo_root, base, branch)
    return memorise(_comptes, (repo_root, base_rev, tip),
                    lambda: _count(repo_root, base_rev, tip))


def _code_memorise(repo_root: str, base: str, tip: str) -> int:
    """`_fichiers_de_code` mémorisé comme le compte de commits : (dépôt, base, tip) immuable."""
    return memorise(_codes, (repo_root, base, tip),
                    lambda: _fichiers_de_code(repo_root, base, tip))


def _fichiers_de_code(repo_root: str, base: str, tip: str) -> int:
    """Fichiers de CODE changés sur la branche depuis son ancêtre commun avec la base."""
    from .api_tickets.livraison import est_du_code, fichiers_meta
    try:
        res = _run(repo_root, "diff", "--name-only", f"{base}...{tip}")
    except (OSError, subprocess.SubprocessError) as exc:
        _log.warning("unmerged: diff %s...%s impossible dans %s : %s", base, tip, repo_root, exc)
        return 0
    meta = fichiers_meta()
    return sum(1 for f in (res.stdout or "").splitlines() if f and est_du_code(f, meta))


def scan(tickets: Iterable[dict]) -> dict[str, Any]:
    """Compte les commits non intégrés de chaque ticket, EN PLACE. Rend ses statistiques.

    L'appelant (le tick) possède les tickets et leur persistance : ce module ne fait aucun I/O
    de store, ce qui le rend testable contre un vrai dépôt sans toucher à la base.
    """
    stats = {"tickets": 0, "scanned": 0, "skipped": 0, "with_commits": 0}
    with une_passe():
        for ticket in tickets:
            stats["tickets"] += 1
            stats[scan_ticket(ticket)] += 1
            if (ticket.get("delivery") or {}).get("code_files_ahead"):
                stats["with_commits"] += 1
    return stats
