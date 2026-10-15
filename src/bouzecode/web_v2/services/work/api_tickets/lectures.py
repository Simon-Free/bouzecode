# [desc] Lectures PURES des tickets (store seul, ni git ni session) : liste filtrée et paginée par curseur, fiche détaillée (runs + runs `legacy` en lecture seule), runs, occupation d'un projet. [/desc]
"""Spec §6.1 / §6.2, critère §10 n° 1 : aucune de ces lectures n'écrit (ni store, ni git, ni
process). `delivery` est servi tel que calculé la dernière fois (fin de run, tick, refresh).

Runs `legacy` (limite L2 (c)) : un même `agent_id` rangé dans plusieurs tickets avant L2 n'a
gardé qu'un propriétaire dans la table `runs` ; ses autres occurrences restent sous
`legacy.runs` du ticket. Elles sont servies à part (`legacy_runs`, `legacy: true`), en lecture
seule : aucune transition ne les touche."""
from __future__ import annotations

from .. import tickets
from ..etat_ticket import vue
from ..fsm import etats
from .refus import Refus

LIMITE_DEFAUT, LIMITE_MAX = 100, 500


def _entier(valeur, defaut: int) -> int:
    texte = str(valeur or "").strip()
    return int(texte) if texte.isdigit() else defaut


def lister(slug: str, state: str = "", archived: str = "", parent: str = "",
           limit=None, cursor=None, complet: bool = False) -> dict:
    """{tickets: [résumé], next_cursor}. `state` : un ou plusieurs états séparés par des
    virgules ; `archived` : "1" seulement les archivés, "0" (défaut) les actifs, "all" tout."""
    etats_voulus = {e for e in str(state or "").split(",") if e}
    inconnus = etats_voulus - set(etats.ETATS)
    if inconnus:
        raise Refus("etat_inconnu", f"état(s) inconnu(s) : {', '.join(sorted(inconnus))}", 400,
                    attendus=list(etats.ETATS))
    garder_archives = str(archived or "0")
    lignes = []
    for ticket in tickets.list_tickets(slug, include_archived=garder_archives != "0"):
        if garder_archives == "1" and not ticket.get("archived"):
            continue
        if etats_voulus and ticket.get("state") not in etats_voulus:
            continue
        if parent and (ticket.get("parent") or "") != parent.removeprefix("agent/"):
            continue
        lignes.append(ticket)
    debut = _entier(cursor, 0)
    taille = min(max(_entier(limit, LIMITE_DEFAUT), 1), LIMITE_MAX)
    page = lignes[debut:debut + taille]
    suite = debut + taille if debut + taille < len(lignes) else None
    forme = (lambda t: {**t, **vue(t)}) if complet else resume
    return {"tickets": [forme(t) for t in page], "next_cursor": str(suite) if suite else None,
            "total": len(lignes)}


def resume(ticket: dict) -> dict:
    corps = tickets.ticket_summary(ticket)
    for cle in ("delivery", "micro_id", "profile", "model"):
        if ticket.get(cle):
            corps[cle] = ticket[cle]
    return corps


def runs_legacy(ticket: dict) -> list[dict]:
    anciens = ((ticket.get("legacy") or {}).get("runs") or []) if isinstance(
        ticket.get("legacy"), dict) else []
    return [{**run, "legacy": True, "lecture_seule": True} for run in anciens
            if isinstance(run, dict)]


def fiche(ticket: dict) -> dict:
    """La fiche : le ticket à plat (forme historique) ET les blocs de la spec (§6.2)."""
    projection = {**ticket, **vue(ticket)}
    return {**projection, "ticket": projection, "runs": ticket.get("runs") or [],
            "legacy_runs": runs_legacy(ticket), "delivery": ticket.get("delivery"),
            "integration": ticket.get("integration")}


def runs(ticket: dict) -> dict:
    return {"runs": ticket.get("runs") or [], "legacy_runs": runs_legacy(ticket)}


def occupation(slug: str, project: dict) -> dict:
    """Les runs vivants du projet, leur isolation, où ils écrivent (cwd, branche) — ce qu'un
    manager lit pour CHOISIR l'isolation de son prochain enfant (§5.6)."""
    lignes = []
    for ticket in tickets.list_tickets(slug):
        if ticket.get("state") not in etats.ACTIFS:
            continue
        meta = ticket.get("worktree") if isinstance(ticket.get("worktree"), dict) else {}
        run = next((r for r in ticket.get("runs") or [] if r.get("state") != "ended"), None)
        lignes.append({"agent_id": (run or {}).get("agent_id", ""), "ticket_id": ticket["id"],
                       "state": ticket["state"], "isolation": ticket.get("isolation") or "shared",
                       "cwd": meta.get("worktree") or project["path"],
                       "branch": meta.get("branch") or ""})
    return {"runs": lignes}
