# [desc] Clore / rouvrir un ticket : transitions `closed` / `abandoned` / `reopened` de ticket_fsm, idempotentes et réversibles, sans jamais toucher au worktree (C5a). [/desc]
"""`POST …/close {outcome, reason?}` et `POST …/reopen` (spec ticketing §5.5).

Clore n'écrit que l'état : `closed` (outcome `accepted`, depuis un ticket livré) ou `abandoned`
(depuis tout ticket qui n'a plus de run en vol). Rouvrir rend `delivered` (ou `created` pour un
ticket abandonné qui n'a jamais eu de run). Le worktree n'est jamais modifié. Une transition
non listée (clore « accepté » un ticket arrêté, clore un ticket dont l'agent tourne) est
refusée en 409 `transition_refusee`, avec l'état courant.

Clore est aussi LA PORTE DE SORTIE du garde-fou de clôture (`closure_guard.force_closure`) : le
geste est humain, sur le ticket exact, et la clôture forcée est tracée (raison
`cloture_forcee` + événement du journal)."""
from __future__ import annotations

from . import closure_guard, ticket_fsm
from .fsm import etats

ISSUES = ("accepted", "abandoned")
#: Événements du journal : la clôture forcée, et sa levée par une réouverture (limite L2 (b)).
CLOTURE_FORCEE, CLOTURE_FORCEE_LEVEE = "closure_forced", "closure_forced_reopened"


def clore(slug: str, ticket: dict, outcome: str, reason: str = "", actor: str = "utilisateur",
          version: int | None = None) -> dict:
    """Clôt le ticket (idempotent : reclore avec la même issue ne change rien).
    `ValueError` sur une issue inconnue ; `TransitionRefusee` depuis un état incompatible."""
    if outcome not in ISSUES:
        raise ValueError(f"issue inconnue : {outcome!r} (attendu : {', '.join(ISSUES)})")
    forced = closure_guard.force_closure(slug, ticket) if outcome == "accepted" else ""
    if outcome == "accepted":
        frais = ticket_fsm.appliquer(slug, ticket["id"], etats.CLOSE, actor, version=version,
                                     code="cloture_forcee" if forced else "accepte",
                                     message=reason, **({"details": {"enfants": forced}}
                                                        if forced else {}))
    else:
        frais = ticket_fsm.appliquer(slug, ticket["id"], etats.ABANDON, actor, version=version,
                                     message=reason)
    if forced:  # trace DURABLE : la raison `cloture_forcee` s'efface à la réouverture
        ticket_fsm.noter(slug, ticket["id"], CLOTURE_FORCEE, actor, enfants=forced, raison=reason)
    ticket.update(frais)
    return {"ok": True, "id": ticket["id"], "done": True, "outcome": outcome,
            "closure_forced": forced, "state": frais["state"], "version": frais["version"]}


def rouvrir(slug: str, ticket: dict, actor: str = "utilisateur",
            version: int | None = None) -> dict:
    """Rouvre le ticket (idempotent : un ticket ouvert reste tel quel). Worktree, branche et
    historique sont intacts."""
    if ticket.get("state") in etats.CLOS:
        raison = ticket.get("state_reason") if isinstance(ticket.get("state_reason"), dict) else {}
        ticket.update(ticket_fsm.appliquer(slug, ticket["id"], etats.REOPENED, actor,
                                           version=version))
        if raison.get("code") == "cloture_forcee":
            ticket_fsm.noter(slug, ticket["id"], CLOTURE_FORCEE_LEVEE, actor,
                             enfants=(raison.get("details") or {}).get("enfants"))
    return {"ok": True, "id": ticket["id"], "done": False, "state": ticket.get("state"),
            "version": ticket.get("version")}
