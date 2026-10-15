# [desc] La machine à états du ticket, en données : 12 états, les événements, la table des transitions autorisées (spec ticketing §4). Pure, zéro I/O. [/desc]
"""L'unique énumération d'état d'un ticket et la table de ses transitions (spec §4, B2).

Tout ce qui change `ticket.state` passe par `ticket_fsm.transition`, qui consulte CETTE table
et refuse le reste. Les états `queued` et `frozen` de la spec arriveront avec les arbres de
sous-agents (lot R5b) : ils n'existent pas encore ici.

ARBITRAGE (documenté dans `services/work/README.md`) : tout geste qui crée un NOUVEAU run —
lancement, relance, run `merge_fix` sur un conflit — passe par `provisioning`. La spec dessine
certaines relances directement vers `running` ; or c'est en basculant l'état SOUS VERROU au
moment de la demande que le serveur garantit « un seul run vivant » (C10 : un second lancement
voit `provisioning` et reçoit 409 `deja_actif`). Les gestes qui réutilisent le run existant
(message à un agent livré, réponse à une question) vont, eux, droit à `running`.

« Conflit résolu, prêt à intégrer » n'est pas un état : c'est `conflict` avec
`state_reason.code == "conflit_resolu"` (posé par le watchdog quand le merge est conclu dans le
worktree). Intégrer depuis là rejoue `conflict_cleared` (→ delivered) puis `integrate_started`.
"""
from __future__ import annotations

CREATED, PROVISIONING, LAUNCH_FAILED = "created", "provisioning", "launch_failed"
RUNNING, AWAITING_INPUT = "running", "awaiting_input"
DELIVERED, IDLE_NO_DELIVERY, STOPPED = "delivered", "idle_no_delivery", "stopped"
INTEGRATING, CONFLICT, CLOSED, ABANDONED = "integrating", "conflict", "closed", "abandoned"

ETATS = (CREATED, PROVISIONING, LAUNCH_FAILED, RUNNING, AWAITING_INPUT, DELIVERED,
         IDLE_NO_DELIVERY, STOPPED, INTEGRATING, CONFLICT, CLOSED, ABANDONED)

#: Un run (ou un lancement) est en vol : aucun second lancement possible (C10).
ACTIFS = frozenset({PROVISIONING, RUNNING, AWAITING_INPUT, INTEGRATING})
#: Plus rien ne bougera sans un geste : livré, arrêté, intégré, abandonné…
TERMINAUX_POUR_LE_PARENT = frozenset({LAUNCH_FAILED, DELIVERED, IDLE_NO_DELIVERY, STOPPED,
                                      CONFLICT, CLOSED, ABANDONED})
#: Fin du cycle de vie (rouvrable seulement).
CLOS = frozenset({CLOSED, ABANDONED})

#: Les gestes et constats qui font bouger l'état (noms des événements du journal, spec §3.3).
LAUNCHED, STARTED = "launched", "started"
QUESTION_ASKED, ANSWERED, RUN_ENDED = "question_asked", "answered", "run_ended"
AWAITING_CHILDREN, MESSAGE_SENT = "awaiting_children", "message_sent"
STOP, CRASHED = "stopped", "crashed"
INTEGRATE_STARTED, INTEGRATED, INTEGRATE_FAILED = "integrate_started", "integrated", "integrate_failed"
CONFLICT_DETECTED, CONFLICT_RESOLVED, CONFLICT_CLEARED = "conflict", "conflict_resolved", "conflict_cleared"
CLOSE, ABANDON, REOPENED = "closed", "abandoned", "reopened"
LAUNCH_FAILED_EVENT = "launch_failed"

_RELANCABLES = (CREATED, LAUNCH_FAILED, DELIVERED, IDLE_NO_DELIVERY, STOPPED, CONFLICT)
_ABANDONNABLES = (CREATED, LAUNCH_FAILED, DELIVERED, IDLE_NO_DELIVERY, STOPPED, CONFLICT)

#: (état courant, événement) -> état(s) d'arrivée possibles. Une paire absente est REFUSÉE.
TRANSITIONS: dict[tuple[str, str], tuple[str, ...]] = {
    **{(etat, LAUNCHED): (PROVISIONING,) for etat in _RELANCABLES},
    (PROVISIONING, STARTED): (RUNNING,),
    (PROVISIONING, LAUNCH_FAILED_EVENT): (LAUNCH_FAILED,),
    (PROVISIONING, STOP): (STOPPED,),
    (RUNNING, QUESTION_ASKED): (AWAITING_INPUT,),
    (RUNNING, RUN_ENDED): (DELIVERED, IDLE_NO_DELIVERY),
    # Le hook de fin arrive APRÈS que le watchdog a classé le run `stopped{crashed}` : s'il
    # PROUVE une réponse finale, il corrige (lot L5) ; sans livraison, rien ne bouge.
    (STOPPED, RUN_ENDED): (DELIVERED,),
    (RUNNING, AWAITING_CHILDREN): (RUNNING,),
    (RUNNING, STOP): (STOPPED,),
    (RUNNING, CRASHED): (STOPPED,),
    (AWAITING_INPUT, ANSWERED): (RUNNING,),
    (AWAITING_INPUT, STOP): (STOPPED,),
    (AWAITING_INPUT, CRASHED): (STOPPED,),
    # Reprise du MÊME agent (message à un agent livré / arrêté, réveil d'un manager garé) :
    # depuis `running`, c'est un manager qui attendait ses sous-agents, ou un run remplacé.
    **{(etat, MESSAGE_SENT): (RUNNING,) for etat in (DELIVERED, IDLE_NO_DELIVERY, STOPPED, RUNNING)},
    (DELIVERED, INTEGRATE_STARTED): (INTEGRATING,),
    (DELIVERED, CLOSE): (CLOSED,),
    (INTEGRATING, INTEGRATED): (CLOSED,),
    (INTEGRATING, CONFLICT_DETECTED): (CONFLICT,),
    (INTEGRATING, INTEGRATE_FAILED): (DELIVERED,),
    (CONFLICT, CONFLICT_RESOLVED): (CONFLICT,),
    (CONFLICT, CONFLICT_CLEARED): (DELIVERED,),
    **{(etat, ABANDON): (ABANDONED,) for etat in _ABANDONNABLES},
    (CLOSED, REOPENED): (DELIVERED,),
    (ABANDONED, REOPENED): (DELIVERED, CREATED),
}

EVENEMENTS = tuple(sorted({evenement for _etat, evenement in TRANSITIONS}))

#: Raison posée par défaut quand l'événement n'en fournit pas (`None` = raison effacée).
_RAISON_PAR_DEFAUT = {
    LAUNCH_FAILED_EVENT: "lancement_echoue", STOP: "interrupted", CRASHED: "crashed",
    AWAITING_CHILDREN: "attend_enfants", INTEGRATE_FAILED: "merge_echoue",
    CONFLICT_DETECTED: "conflit", CONFLICT_RESOLVED: "conflit_resolu", CLOSE: "accepte",
    ABANDON: "abandonne",
}


def cible(etat: str, evenement: str, delivered: bool = True, a_des_runs: bool = True) -> str | None:
    """L'état d'arrivée de `evenement` depuis `etat`, ou None si la transition n'est pas listée.
    Deux transitions dépendent d'une donnée : la fin d'un run (livré ou non, décidé par
    `close_reasons.issue_de_fin`) et la réouverture d'un ticket abandonné (avec ou sans run)."""
    possibles = TRANSITIONS.get((etat, evenement))
    if not possibles:
        return None
    if evenement == RUN_ENDED and etat == STOPPED:
        return DELIVERED if delivered else None
    if evenement == RUN_ENDED:
        return DELIVERED if delivered else IDLE_NO_DELIVERY
    if evenement == REOPENED and etat == ABANDONED:
        return DELIVERED if a_des_runs else CREATED
    return possibles[0]


def raison_par_defaut(evenement: str) -> str | None:
    return _RAISON_PAR_DEFAUT.get(evenement)
