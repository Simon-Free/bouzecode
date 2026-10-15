# [desc] Applique le garde-fou de périmètre à un ticket qui vient d'être dispatché : flags + commentaires. [/desc]
"""Point d'entrée serveur du garde-fou de périmètre.

`review_dispatch`, juste après la création du ticket enfant, SIGNALE (drapeau + commentaire +
avertissement au manager) un recouvrement avec un frère, quel que soit son état.

`refus_de_doublon`, AVANT la création, REFUSE un second enfant sur le périmètre d'un frère
ENCORE ACTIF du même parent. Essai du 2026-09-25 : la racine 6bafe9cd a lancé 0f852f4d puis
a139daa2 (même périmètre, 42 %, même nom « scraper-fix ») ; l'avertissement « ⚠️ PÉRIMÈTRE EN
DOUBLON » est arrivé dans un résultat qui commençait par « Ticket a139daa2 dispatché », la
racine l'a lu comme un refus, et deux enfants ont réécrit le même scraper pendant 50 minutes.
Le refus est déterministe (même seuil que le signal, frères ACTIFS seulement : relancer après
une livraison ou un échec reste libre, deux périmètres disjoints passent) et contournable par
le parent qui l'assume : `doublon_assume` porte sa raison, écrite sur le ticket.

`verrou_de_fratrie` sérialise, pour un même parent, le refus ET la création : les N Agent d'un
même message partent ensemble (dispatcher DAG, `lot_simultane`), leurs POST /api/projects/<slug>/tickets
arrivent en même temps ; sans verrou, chacun contrôlait une fratrie où l'autre n'existait pas
encore, et deux enfants au même périmètre étaient acceptés.
"""
from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Any, Iterator

from . import overlap, readonly

#  Une raison, pas un mot : « ok », « oui » ou « voulu » ne disent pas en quoi le livrable diffère.
RAISON_MIN = 15

#  Un verrou par parent : deux parents différents dispatchent toujours en parallèle.
_verrous_guard = threading.Lock()
_verrous: dict[str, threading.Lock] = {}


@contextmanager
def verrou_de_fratrie(parent: str) -> Iterator[None]:
    """Tenu autour de `refus_de_doublon` ET de la création du ticket : un frère lancé dans le
    même lot n'est contrôlé qu'une fois le précédent créé (donc visible, « en lancement »).
    `agent/<id>` et `<id>` désignent le même parent. Sans parent agent, rien à sérialiser."""
    cle = (parent or "").removeprefix("agent/")
    if not cle or cle.startswith("dispatcher:"):
        yield
        return
    with _verrous_guard:
        verrou = _verrous.setdefault(cle, threading.Lock())
    with verrou:
        yield


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
    tickets_svc.poser(slug, ticket, **{flag: valeur})
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


def _freres_actifs(parent: str) -> list[dict[str, Any]]:
    """Les enfants de `parent` dont le travail peut encore changer, avec leur lancement."""
    from ..work import enfants
    actifs = []
    for slug, ticket in enfants.tickets_enfants(parent):
        if ticket.get("archived"):
            continue
        if enfants.etat(ticket) in enfants.ACTIFS:
            actifs.append(ticket)
    return actifs


def _decrire(doublon: dict[str, Any], freres: dict[str, dict]) -> str:
    ticket = freres.get(doublon["id"]) or {}
    lancement = ticket.get("lancement") or {}
    quand = f" au tour {lancement['tour']}" if lancement.get("tour") else ""
    nom = f" sous le nom « {lancement['nom']} »" if lancement.get("nom") else ""
    return (f"  - {doublon['id']} — lancé par toi{quand}{nom}, ENCORE ACTIF, "
            f"{int(doublon['score'] * 100)} % de périmètre commun — {doublon['title'][:80]}")


def refus_de_doublon(prompt: str, parent: str, raison: str = "") -> str:
    """Motif du refus ("" = le dispatch peut avoir lieu). Un parent qui n'est pas un agent
    (création manuelle depuis l'interface) n'a pas de fratrie : l'humain assume son découpage."""
    if not parent or parent.startswith("dispatcher:"):
        return ""
    freres = _freres_actifs(parent)
    doublons = overlap.overlapping_siblings(prompt, freres)
    raison = (raison or "").strip()
    if not doublons or len(raison) >= RAISON_MIN:
        return ""
    par_id = {t.get("id"): t for t in freres}
    lignes = "\n".join(_decrire(d, par_id) for d in doublons)
    premier = doublons[0]["id"]
    trop_courte = (f"\n(Raison « {raison} » trop courte : dis en quoi ce livrable diffère.)"
                   if raison else "")
    return ("PÉRIMÈTRE EN DOUBLON — AUCUN enfant n'a été créé. Ce brief recouvre celui "
            f"d'un enfant que tu as déjà lancé et qui travaille encore :\n{lignes}\n"
            f"Même livrable : attends-le (CheckAgentResult(task_id='{premier}', wait=true)) "
            f"ou réoriente-le (MessageAgent(ticket_id='{premier}', text=…)). Livrable "
            "réellement distinct : relance Agent avec doublon_assume='<en quoi ce travail "
            f"diffère du sien>'.{trop_courte}")
