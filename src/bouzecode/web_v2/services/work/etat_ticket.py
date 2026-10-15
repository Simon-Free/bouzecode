# [desc] Projection PURE de `ticket.state` (+ state_reason) vers ce que l'écran et les agents lisent : statut historique, clé du lexique, libellé, ton. Aucune redérivation. [/desc]
"""Le libellé d'un ticket N'EST PLUS DÉRIVÉ de ses drapeaux et de la vivacité de ses agents : il
est la projection de son état persisté (spec B2). Toutes les surfaces — fiche et liste des
tickets, `/api/agents/tree`, `/api/lignes`, `/api/inbox`, Bureau — appellent `vue(ticket)` et
disent donc la même chose au même instant (critère 2).

Deux vocabulaires, une seule source :
  * `status` — le mot historique (« en cours », « à relire », « planté »…), gardé tel quel pour
    les scripts et les agents qui le lisent ;
  * `status_ui` / `libelle_statut` — la clé et le mot du lexique unique (`lexique.LEXIQUE`)."""
from __future__ import annotations

from .fsm import etats

#: state → mot historique ; un code de `state_reason` peut le préciser (`_PAR_RAISON`).
_STATUT = {
    etats.CREATED: "à faire", etats.PROVISIONING: "préparation",
    etats.LAUNCH_FAILED: "lancement échoué", etats.RUNNING: "en cours",
    etats.AWAITING_INPUT: "attend réponse", etats.DELIVERED: "à relire",
    etats.IDLE_NO_DELIVERY: "arrêté sans finir", etats.STOPPED: "planté",
    etats.INTEGRATING: "intégration", etats.CONFLICT: "conflit",
    etats.CLOSED: "terminé", etats.ABANDONED: "abandonné",
}
_PAR_RAISON = {
    (etats.RUNNING, "attend_enfants"): "en attente des enfants",
    (etats.DELIVERED, "merge_bloque"): "merge bloqué",
    (etats.DELIVERED, "merge_echoue"): "merge bloqué",
    (etats.DELIVERED, "cloture_bloquee"): "clôture bloquée",
    (etats.DELIVERED, "livraison_non_commitee"): "livraison non commitée",
    (etats.STOPPED, "interrupted"): "arrêté",
    (etats.STOPPED, "killed"): "arrêté",
    (etats.STOPPED, "arret_preparation"): "arrêté",
    (etats.STOPPED, "introuvable"): "agent introuvable",
    (etats.CONFLICT, "conflit_resolu"): "conflit résolu",
}


def code_raison(ticket: dict) -> str:
    raison = ticket.get("state_reason")
    return str(raison.get("code") or "") if isinstance(raison, dict) else ""


def statut(ticket: dict) -> str:
    """Le mot historique du ticket, projection de (state, state_reason.code)."""
    state = str(ticket.get("state") or "")
    return _PAR_RAISON.get((state, code_raison(ticket))) or _STATUT.get(state, state)


def vue(ticket: dict) -> dict:
    """Les champs d'état servis par TOUTES les surfaces pour un ticket."""
    from .lexique import LEXIQUE, statut_ticket
    mot = statut(ticket)
    cle = statut_ticket(mot)
    entree = LEXIQUE.get(cle) or {}
    return {"state": str(ticket.get("state") or ""), "state_reason": ticket.get("state_reason"),
            "version": ticket.get("version"), "status": mot, "status_ui": cle,
            "libelle_statut": entree.get("mot", mot), "ton_statut": entree.get("ton", "neutral")}


def actif(ticket: dict) -> bool:
    """Un run (ou un lancement, ou un merge) est en vol : pas de second lancement."""
    return ticket.get("state") in etats.ACTIFS


def integre(ticket: dict) -> bool:
    """Le travail du ticket a été fusionné dans sa base (clos par un merge)."""
    return ticket.get("state") == etats.CLOSED and code_raison(ticket) in ("integre", "ephemere")


def vue_rattachee(ticket: dict | None) -> dict:
    """Les mêmes champs, PRÉFIXÉS, pour une surface dont l'objet n'est pas le ticket lui-même
    (nœud d'agent de l'arbre, ligne du Bureau, entrée de l'inbox) : `ticket_state`,
    `ticket_state_reason`, `ticket_status_ui`, `libelle_ticket`. Vide sans ticket."""
    if not ticket:
        return {}
    projection = vue(ticket)
    return {"ticket_state": projection["state"], "ticket_state_reason": projection["state_reason"],
            "ticket_status": projection["status"], "ticket_status_ui": projection["status_ui"],
            "libelle_ticket": projection["libelle_statut"]}
