"""Libellé de statut d'un ticket, dérivé de son état persisté (pur, aucune I/O).

Extrait de `tickets.py` (qui le ré-exporte : `tickets.derive_status` reste l'API publique).
Une seule règle gouverne ce module : le statut ne MENT jamais. Il ne masque ni un échec
derrière `done`, ni un succès derrière `crashed`, et il n'annonce une attente que si
quelqu'un est réellement attendu."""
from __future__ import annotations


def _manager_has_children(runs: list[dict], parents_with_children: set[str] | None) -> bool:
    """Le manager qui a joué ces runs a-t-il RÉELLEMENT dispatché au moins un enfant ?

    `parents_with_children` = les agent_id parents d'au moins un ticket du projet
    (`tickets.parent_agent_ids`). `None` = l'appelant ne s'est pas renseigné : on répond
    « oui » pour conserver EXACTEMENT le comportement historique — un appelant qui ne sait
    pas ne doit pas faire changer d'avis le board."""
    if parents_with_children is None:
        return True
    return bool({run.get("agent_id") for run in runs} & parents_with_children)


def derive_status(ticket: dict, parents_with_children: set[str] | None = None,
                  liveness_state: str = "") -> str:
    """Libellé de statut du ticket. `liveness_state` = la vivacité croisée du ticket
    (`liveness.classify_ticket`, seule à savoir si un process a survécu et s'il a stampé une
    clôture) ; vide = l'appelant ne s'est pas renseigné → comportement historique inchangé."""
    # « En attente d'action » PRIME sur done : un ticket manuellement marqué done alors que
    # le merge était bloqué (needs_attention) ou qu'un faux crash n'a jamais été retiré doit
    # rester VISIBLE comme actionnable, pas masqué en « terminé » (cf. cas d677b7d5 / 86c37f5a).
    if ticket.get("crashed"):
        return "planté"  # crash détecté par le watchdog (agent mort sans clôture)
    meta = ticket.get("worktree")
    if isinstance(meta, dict) and meta.get("state") == "needs_attention":
        return "merge bloqué"  # validé mais merge impossible : réintégration manuelle requise
    # Clôture REFUSÉE par le garde-fou : un enfant de ce manager a planté sans rien livrer
    # (`closure_guard.refuse_closure`, drapeau `closure_blocked`). AVANT `done`, comme
    # `crashed`/`needs_attention` : c'est précisément une clôture qui ne doit JAMAIS pouvoir
    # se présenter comme « terminé » (cas beefcafe). Un blocage muet serait un nouveau bug.
    if ticket.get("closure_blocked"):
        return "clôture bloquée"
    # Travail LIVRÉ mais toujours pas commité : la récolte de livraison a échoué (index git
    # verrouillé, dépôt en vrac) et ces fichiers ne survivront pas au nettoyage du worktree.
    # AVANT `done` comme `crashed` : c'est exactement le mensonge qu'on a payé le 28/07 —
    # un ticket annoncé livré/terminé dont la branche était vide (cf. services/work/delivery.py).
    if ticket.get("uncommitted"):
        return "livraison non commitée"
    # Provisionnement ÉCHOUÉ : aucun agent n'a jamais démarré (`dispatch.record_launch_failure`).
    # AVANT `done` comme `crashed` — et surtout avant la fin de la fonction, qui rendait « à
    # faire » (aucun run) : un ticket mort-né se présentait donc comme un ticket ordinaire en
    # attente, indiscernable d'un ticket jamais lancé, alors qu'il exige une action (cas
    # 60f34332). Le drapeau est retiré dès qu'une relance est en vol (`tickets.set_launching`).
    if ticket.get("launch_failed"):
        return "lancement échoué"
    runs = [r for r in (ticket.get("runs") or []) if isinstance(r, dict)]
    if ticket.get("done"):
        # Un `done` (posé à la main, ou par un hook trop généreux) ne peut PAS transformer un
        # agent mort SANS LIVRAISON en succès : quand la vivacité dit `crashed` sur un ticket
        # qui a bel et bien été joué, on affiche « planté ». Sans cette garde, un run mort à
        # 0 bloc s'annonçait « terminé » — un travail livré annoncé qui n'existe pas.
        if liveness_state == "crashed" and runs:
            return "planté"
        return "terminé"
    if ticket.get("launching"):
        return "en cours"  # worktree+spawn en fond : ticket actif, run pas encore créé
    # (feature develop) un agent qui attend une réponse user est DISTINCT de 'en cours',
    # et prime sur 'en cours' quand les deux coexistent.
    if any(run.get("state") in ("awaiting_input", "awaiting_plan_validation") for run in runs):
        return "attend réponse"
    if any(run.get("state") == "running" for run in runs):
        return "en cours"
    # Un manager/monitor (read-only) ne PRODUIT pas de code : son tour fini ne veut pas dire
    # « à relire » (rien à relire) mais « en attente des enfants » — il sera ré-invoqué par le
    # wake, puis marqué `done` (→ "terminé") quand tous ses enfants seront terminaux.
    #
    # SAUF s'il n'a AUCUN enfant : `wake.process_wakes` n'itère que `_children_by_parent()`,
    # dont les clés sont les parents AYANT des enfants — un manager qui n'a rien dispatché
    # n'y figure pas, n'est donc jamais réveillé ni finalisé, et « en attente des enfants »
    # le fige dans un limbo ni actionnable ni terminal. Il n'attend personne : son tour est
    # fini et son rapport est À LIRE. On ne le marque NI `done` (ce serait un succès inventé)
    # NI `crashed` (un échec inventé) : la suite de la fonction rend le statut honnête
    # (« échec validation » s'il a rendu VERDICT: KO, sinon « à relire »).
    from bouzecode.web_v2.services.work.workflow import NON_CODING_TYPOLOGIES
    if ((ticket.get("typology") or "") in NON_CODING_TYPOLOGIES
            and any(run.get("kind") == "work" for run in runs)
            and _manager_has_children(runs, parents_with_children)):
        return "en attente des enfants"
    # Un validateur n'est plus lancé automatiquement, mais quand le manager en a lancé un,
    # son verdict KO est l'information la plus actionnable : on l'affiche plutôt que « à relire ».
    from bouzecode.web_v2.services.work import integration
    if integration.latest_verdict(ticket) == "KO":
        return "échec validation"
    verdicts = [r.get("verdict") for r in runs if str(r.get("kind", "")).startswith("validate")]
    if verdicts and all(v == "OK" for v in verdicts):
        return "validé"
    if any(run.get("kind") == "work" for run in runs):
        return "à relire"
    return "à faire"
