# [desc] Applique le garde-fou de périmètre à un ticket qui vient d'être dispatché : flags + commentaires. [/desc]
"""Point d'entrée serveur du garde-fou, appelé juste après la création du ticket enfant.

Il SIGNALE, il ne refuse pas. Un refus sur un jugement heuristique bloquerait des dispatches
légitimes (deux tickets voisins mais disjoints) ; un signal coûte un commentaire et rend le
problème visible là où il doit l'être : sur le ticket, et dans le `tool_result` du manager
qui vient de le créer — le seul acteur capable de corriger le découpage.
"""
from __future__ import annotations

from typing import Any

from . import overlap, readonly


def _freres(slug: str, ticket_id: str, parent: str) -> list[dict[str, Any]]:
    """Les autres tickets dispatchés par le MÊME parent. Un parent vide (création
    manuelle depuis l'UI) n'a pas de fratrie : l'humain assume son découpage."""
    if not parent:
        return []
    from ..work import tickets as tickets_svc
    return [t for t in tickets_svc.list_tickets(slug)
            if t.get("parent") == parent and t.get("id") != ticket_id]


def _signaler(slug: str, ticket_id: str, flag: str, valeur: Any, commentaire: str) -> None:
    """Pose le drapeau et le commentaire. Le drapeau rend l'anomalie interrogeable
    (API, UI, audit) ; le commentaire la rend LISIBLE."""
    from ..work import tickets as tickets_svc
    ticket = tickets_svc.get_ticket(slug, ticket_id)
    if ticket is None:
        return
    ticket[flag] = valeur
    tickets_svc.update_ticket(slug, ticket)
    tickets_svc.add_comment(slug, ticket, commentaire, True)


def review_dispatch(slug: str, ticket_id: str, prompt: str, typology: str,
                    parent: str) -> list[str]:
    """Relit un dispatch qui vient d'aboutir. Retourne les avertissements à rendre au manager.

    Deux vérifications, toutes deux mécaniques :
    1. le ticket recouvre-t-il le périmètre d'un frère déjà ouvert ?
    2. son prompt impose-t-il la lecture seule alors que sa typologie accorde l'écriture ?
    """
    avertissements: list[str] = []

    doublons = overlap.overlapping_siblings(prompt, _freres(slug, ticket_id, parent))
    if doublons:
        _signaler(slug, ticket_id, overlap.OVERLAP_FLAG_KEY,
                  [d["id"] for d in doublons], overlap.overlap_comment(doublons))
        avertissements.append(overlap.overlap_warning(doublons))

    outils = readonly.unenforced_read_only(prompt, typology)
    if outils:
        _signaler(slug, ticket_id, readonly.READONLY_FLAG_KEY, outils,
                  readonly.readonly_comment(outils))
        avertissements.append(readonly.readonly_warning(outils))

    return avertissements
