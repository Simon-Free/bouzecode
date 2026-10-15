# [desc] Dérivation PURE de l'état d'une tâche depuis les statuts de ses tickets liés (§4.1).
"""Aucun import I/O, volontairement : c'est la règle du §4.1 de la spec du Bureau, et elle
doit être testable sans base, sans Flask et sans agent. Les libellés d'entrée sont EXACTEMENT
ceux rendus par `etat_ticket.statut` (projection de `ticket.state`) — toute divergence de
vocabulaire ici serait un état de tâche silencieusement faux, pas une erreur."""

from __future__ import annotations

from collections.abc import Iterable

# Un ticket dans l'un de ces états EXIGE une action humaine : la tâche est bloquée.
BLOCKED_STATUSES = frozenset({
    "planté",
    "arrêté",
    "arrêté sans finir",
    "agent introuvable",
    "merge bloqué",
    "clôture bloquée",
    "livraison non commitée",
    "lancement échoué",
    "conflit",
})

# Le travail avance : personne n'a rien à faire pour l'instant.
# « en attente des enfants » n'est PAS dans la table §4.1 (elle a été écrite avant que ce
# libellé existe) : un manager qui attend ses enfants avance, donc `en_cours`. Le classer
# `a_relire` aurait fait remonter dans « à relire » des managers dont il n'y a rien à relire.
ACTIVE_STATUSES = frozenset({"en cours", "préparation", "intégration", "attend réponse",
                             "en attente des enfants"})

# Le travail est rendu et attend MON regard.
REVIEW_STATUSES = frozenset({"à relire", "conflit résolu"})

#  Clos avec succès, ou abandonné par décision : plus rien à faire sur ce ticket.
DONE_STATUSES = frozenset({"terminé", "abandonné"})


def derive_task_state(statuses: Iterable[str]) -> str:
    """État d'une tâche à partir des statuts (`derive_status`) de ses tickets liés.

    Ordre de priorité : `bloquee` > `fait` > `en_cours` > `a_relire` > `a_faire`.

    Le blocage prime sur TOUT, y compris sur l'activité : une tâche dont un ticket a planté
    pendant qu'un autre tourne encore reste `bloquee`, sinon le plantage disparaîtrait derrière
    son frère vivant — exactement le mensonge que `derive_status` refuse déjà ticket par ticket.

    `fait` est PROPOSÉ, jamais imposé : cette fonction ne clôt rien, elle constate que tous les
    tickets sont terminés. La clôture reste une réponse humaine (`close_task`).
    """
    labels = [str(status or "") for status in statuses]
    if not labels:
        return "a_faire"
    if any(label in BLOCKED_STATUSES for label in labels):
        return "bloquee"
    if all(label in DONE_STATUSES for label in labels):
        return "fait"
    if any(label in ACTIVE_STATUSES for label in labels):
        return "en_cours"
    if any(label in REVIEW_STATUSES for label in labels):
        return "a_relire"
    return "a_faire"
