# [desc] Table unique close_reason -> livraison prouvée / ticket avancé / clôture contrôlée. [/desc]
"""Une seule table, trois questions.

Trois ensembles vivaient dans trois modules et répondaient chacun à sa question sans se
connaître : `runner` décidait du code retour, `wake` de l'avancement du ticket, `liveness`
de la vivacité. Ils divergeaient — `ends_turn_tool` était « propre » pour l'un et « planté »
pour l'autre — et `final_answer_over_failed_tool`, introduit le 2026-07-29, ne figurait dans
AUCUN : un agent ayant clos délibérément était rapporté PLANTÉ et son ticket gelé.

Les trois questions restent DISTINCTES, elles ne sont pas redondantes : `text_no_tools` fait
avancer le ticket (le verdict d'un validateur est dans sa prose) sans prouver de livraison
(rc≠0, sinon un validateur clos sur prose basculerait de KO à OK). Ce qui change, c'est
qu'elles sont répondues au même endroit, pour chaque raison, une fois.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Closure:
    """Ce qu'une raison de clôture prouve, pour les trois surfaces qui en décident."""

    proves_delivery: bool   # rc 0 : une réponse finale est prouvée sur disque  (runner)
    advances_ticket: bool   # le reconciler marque le run `completed`           (wake)
    controlled: bool        # la boucle a décidé de clore, pas une mort en vol  (liveness)


_DELIVERED = Closure(proves_delivery=True, advances_ticket=True, controlled=True)
_FORCED = Closure(proves_delivery=False, advances_ticket=False, controlled=True)
_CRASH = Closure(proves_delivery=False, advances_ticket=False, controlled=False)

CLOSURES: dict[str, Closure] = {
    # ── Clôtures explicites : FinalAnswer, ou un autre outil `ends_turn`. ──
    "final_answer": _DELIVERED,
    "final_answer_deferred": _DELIVERED,
    "ends_turn_tool": _DELIVERED,
    # 2026-07-29 — réponse rendue APRÈS 3 relances sur un outil refusé. Classée comme une
    # livraison parce qu'elle en était une jusqu'ici : `loop._fire_completion` l'écrasait en
    # "final_answer". La dégrader en crash serait une régression, pas un correctif — c'est au
    # validateur de juger une livraison dont un outil a manqué, pas au classifieur de geler.
    "final_answer_over_failed_tool": _DELIVERED,
    # ── Clôture sur prose sans tool call. ──
    # LÉGITIME pour un validateur/manager (le verdict est dans le texte) donc le ticket avance,
    # mais aucune FinalAnswer ne prouve de livraison. `wake._is_work_abandoned_mid_turn` la
    # re-route en crash pour les runs `work` : un codeur arrêté en plein tour n'a rien livré.
    "text_no_tools": Closure(proves_delivery=False, advances_ticket=True, controlled=True),
    # ── Fins FORCÉES par la boucle : maîtrisées, mais rien n'a été livré. ──
    "final_answer_nudge_exhausted": _FORCED,
    "final_answer_never_called": _FORCED,
    "meta_only_cap": _FORCED,
    "meta_only_text_close": _FORCED,  # cf. LEGACY_CLOSE_REASONS
    # ── Morts en vol : posées par le runner/l'IPC, jamais par la boucle. ──
    "api_error": _CRASH,
    "cancelled": _CRASH,
    "assistant_none": _CRASH,
    "partial_stream": _CRASH,
}

# Raison absente de la table : rien n'est prouvé. Repli délibérément pessimiste — une clôture
# qu'on ne sait pas nommer ne doit ni valider un rc 0 ni faire avancer un ticket.
UNKNOWN = _CRASH

# Raisons que la boucle NE PRODUIT PLUS mais que des sessions sur disque portent encore.
# Les retirer de la table reclasserait ces sessions en « plantées » : `liveness` lit des
# tickets vieux de plusieurs semaines. Déclarées ICI pour que le garde anti-fantôme
# (tests/web_v2/test_close_reasons_table.py) distingue une survivance ASSUMÉE d'un oubli.
LEGACY_CLOSE_REASONS = frozenset({
    "meta_only_text_close",  # l'arme `text_closes` a été retirée (cf. b83ade94)
})

DELIVERY_CLOSE_REASONS = frozenset(r for r, c in CLOSURES.items() if c.proves_delivery)
ADVANCING_CLOSE_REASONS = frozenset(r for r, c in CLOSURES.items() if c.advances_ticket)
CONTROLLED_CLOSE_REASONS = frozenset(r for r, c in CLOSURES.items() if c.controlled)
CRASH_CLOSE_REASONS = frozenset(r for r, c in CLOSURES.items() if not c.controlled)


def closure(close_reason: str) -> Closure:
    return CLOSURES.get(close_reason or "", UNKNOWN)


def proves_delivery(close_reason: str) -> bool:
    """rc 0 : une réponse finale est prouvée sur disque."""
    return closure(close_reason).proves_delivery


def advances_ticket(close_reason: str) -> bool:
    """Le reconciler peut marquer le run `completed` et laisser `advance()` continuer."""
    return closure(close_reason).advances_ticket


def is_controlled(close_reason: str) -> bool:
    """La boucle a décidé de clore — par opposition à une mort en vol."""
    return closure(close_reason).controlled


def is_crash(close_reason: str) -> bool:
    """Mort en vol NOMMÉE. Une raison inconnue n'en est pas une : l'appelant la traite déjà
    comme non livrée, mais ne doit pas la libeller « plantée » sur la foi d'un nom qu'il ne
    connaît pas."""
    return close_reason in CLOSURES and not CLOSURES[close_reason].controlled
