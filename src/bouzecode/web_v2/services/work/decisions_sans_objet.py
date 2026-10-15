# [desc] « Décision à prendre » sur un worktree / une branche d'agent : une seule ligne ouverte par objet, et archivage automatique (avec trace) quand cet objet n'existe plus. [/desc]
"""Une décision sur un objet qui a disparu ment au Bureau.

Cas réel (essai 3, 2026-09-24/25) : la racine 6bafe9cd a clos trois fois (clôture, réveil,
réveil) et déclaré à chaque fois « Décision à prendre » sur le worktree résiduel de son
enfant, `agent/fee42a91`, sous trois titres différents :

* « Trancher le sort du worktree résiduel agent/fee42a91 (vue Tinder non commitée…) »
* « Trancher le sort du worktree résiduel agent/fee42a91 (brouillon non commité) »
* « Worktree résiduel agent/fee42a91 : le garder ou le supprimer ? »

L'anti-doublon de `cloture_micros` compare les TITRES : il ne pouvait pas les rapprocher. Et le
worktree comme la branche avaient déjà disparu (intégration de l'enfant) : les trois lignes
restaient pourtant « à décider ».

Ce module rapproche les décisions par leur OBJET — le ticket dont elles nomment la branche
`agent/<id>` ou le worktree `…/worktrees/<dépôt>/<id>` — et le tick du watchdog :

* archive (« abandonnée », trace visible) une décision dont le worktree ET la branche
  n'existent plus ;
* archive les doublons d'une décision encore ouverte sur le même objet, en gardant la plus
  ancienne.

Garde-fous communs avec `brouillons_integres` : jamais une tâche lancée, jamais une tâche
rouverte après un archivage automatique ; objet non vérifiable (ticket ou dépôt inconnu) =
on ne touche à rien.
"""
from __future__ import annotations

import re
import subprocess
from datetime import datetime
from pathlib import Path

from . import brouillons_integres, micros

_OBJET = re.compile(r"(?<![\w/])agent/([0-9a-f]{8})(?![\w/-])"
                    r"|worktrees[\\/][^\\/\s]+[\\/]([0-9a-f]{8})(?![\w-])")
ETATS_OUVERTS = ("brouillon", "prete")


def objet_de(titre: str, corps: str = "") -> str:
    """Le ticket dont la décision tranche le worktree / la branche ; titre d'abord."""
    for texte in (titre, corps):
        trouve = _OBJET.search(str(texte or ""))
        if trouve:
            return trouve.group(1) or trouve.group(2)
    return ""


def _ouvertes() -> list[dict]:
    """Décisions jamais lancées ni déjà archivées automatiquement, de la plus ancienne à la
    plus récente, avec leur objet."""
    with micros._tx() as conn:
        lignes = conn.execute(
            "SELECT m.id, m.titre, m.corps, m.macro_id FROM micros m"
            " WHERE m.decision = 1 AND m.etat IN ('brouillon', 'prete')"
            " AND NOT EXISTS (SELECT 1 FROM micro_tickets t WHERE t.micro_id = m.id)"
            " AND NOT EXISTS (SELECT 1 FROM micro_archivages_auto a WHERE a.micro_id = m.id)"
            " ORDER BY m.created_at, m.rowid").fetchall()
    return [{"id": l[0], "titre": l[1], "macro_id": l[3] or "", "objet": objet_de(l[1], l[2])}
            for l in lignes]


def decision_ouverte_sur(objet: str, macro_id: str) -> str:
    """Id de la décision déjà ouverte sur cet objet dans ce chantier, `""` sinon."""
    if not objet:
        return ""
    return next((d["id"] for d in _ouvertes()
                 if (d["objet"], d["macro_id"]) == (objet, macro_id or "")), "")


def _branche_existe(repo: str, branche: str) -> bool:
    rendu = subprocess.run(["git", "-C", repo, "rev-parse", "--verify", "--quiet",
                            f"refs/heads/{branche}"], capture_output=True, text=True)
    return rendu.returncode == 0


def _quand() -> str:
    return datetime.now().strftime("le %d/%m/%Y à %H:%M")


def _existe(chemin: str) -> bool:
    return bool(chemin) and Path(chemin).exists()


def _lieux(ticket: dict) -> tuple[str, str, str]:
    """`(dépôt, worktree, branche)` du ticket, chaînes vides si inconnus."""
    meta = ticket.get("worktree") or {}
    branche = meta.get("branch") or f"agent/{ticket.get('id') or ''}"
    return str(meta.get("repo_root") or ""), str(meta.get("worktree") or ""), str(branche)


def disparition(ticket: dict | None) -> str:
    """Trace si le worktree ET la branche du ticket n'existent plus ; `""` s'ils existent
    encore ou si on ne peut pas le vérifier (pas de ticket, dépôt introuvable)."""
    repo, worktree, branche = _lieux(ticket or {})
    if not _existe(repo):
        return ""
    if _existe(worktree) or _branche_existe(repo, branche):
        return ""
    lieu = f"le worktree {worktree} et la branche {branche}" if worktree else f"la branche {branche}"
    return (f"Archivée automatiquement : décision sans objet — {lieu} n'existent plus "
            f"(constaté {_quand()}).")


def _groupes(ouvertes: list[dict]) -> dict[tuple[str, str], list[dict]]:
    groupes: dict[tuple[str, str], list[dict]] = {}
    for decision in ouvertes:
        if decision["objet"]:
            groupes.setdefault((decision["objet"], decision["macro_id"]), []).append(decision)
    return groupes


def _archiver(decision: dict, texte: str) -> bool:
    cible = {"ticket_id": decision["objet"], "branche": f"agent/{decision['objet']}"}
    return brouillons_integres.archiver_avec_trace(decision["id"], cible, texte,
                                                   etat="abandonnee")


def _traiter(lot: list[dict], ticket: dict | None) -> list[str]:
    """Tout le lot si l'objet a disparu ; sinon les doublons de la plus ancienne."""
    trace = disparition(ticket)
    if trace:
        return [d["id"] for d in lot if _archiver(d, trace)]
    garde = lot[0]
    doublon = (f"Archivée automatiquement : doublon de la décision « {garde['titre']} » "
               f"({garde['id']}), même objet agent/{garde['objet']}.")
    return [d["id"] for d in lot[1:] if _archiver(d, doublon)]


def balayer() -> list[str]:
    """Tick du watchdog. Rend les ids archivés. Aucune lecture de ticket sans candidat."""
    groupes = _groupes(_ouvertes())
    if not groupes:
        return []
    from . import _persistence
    par_id = {str(t.get("id") or ""): t for _slug, t in _persistence.all_tickets()}
    archivees: list[str] = []
    for (objet, _macro), lot in groupes.items():
        archivees.extend(_traiter(lot, par_id.get(objet)))
    return archivees
