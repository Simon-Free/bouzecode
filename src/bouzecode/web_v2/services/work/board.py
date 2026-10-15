# [desc] Le board du Bureau : les tâches et leurs états dérivés. Aucun git, aucun LLM, aucun agent_tree.
"""Chemin de LECTURE, budget §5 : trois requêtes au total (les tâches, les liens, tous les
tickets), aucune écriture, aucun `refresh=True` (qui toucherait le disque des sessions agent),
aucun appel git ni LLM, et surtout aucun appel à `/api/agents/tree`.

Le board ne persiste PAS l'état dérivé : un GET qui écrit prendrait un write-lock SQLite sur le
chemin le plus chaud de la page pour un résultat recalculable en mémoire."""

from __future__ import annotations

import logging
from datetime import datetime

from bouzecode.web_v2.services.horodatage import age_s, maintenant_iso

from . import _persistence, decisions as decisions_service, tasks as tasks_service
from ._status import derive_status
from ._task_state import derive_task_state

# Alias obligatoire : `decisions` est déjà le nom de la CLÉ du payload rendu ci-dessous.
_log = logging.getLogger(__name__)

STATES = ("bloquee", "en_cours", "a_relire", "a_faire", "fait")


def _waiting_s(asked_at: object) -> int | None:
    """Ancienneté d'une carte en secondes, ou `None` quand l'horodatage est inexploitable.

    `None` et pas 0 : « attend depuis 0 s » est un MENSONGE qui met la carte cassée en tête du
    tri d'ancienneté. Une date inexploitable doit coûter une ancienneté inconnue sur UNE carte,
    jamais un board en erreur 500 — le Bureau est justement l'endroit où l'on va quand tout le
    reste va mal.

    Les décisions n'ont pas toutes la même sorte de date : les anciennes portent une date locale
    naïve, les nouvelles une date UTC explicite. `horodatage.age_s` lit les deux (naïve = LOCALE ;
    surtout pas « supposée UTC », ce qui fabriquerait des attentes fantômes de deux heures).
    """
    if not asked_at:
        return None
    if not isinstance(asked_at, str):
        _log.warning("decision: asked_at n'est pas une date (%r), ancienneté inconnue", asked_at)
        return None
    age = age_s(asked_at)
    if age is None:
        _log.warning("decision: asked_at illisible (%r), ancienneté inconnue", asked_at)
        return None
    return max(0, int(age))


def _cards() -> list[dict]:
    """Les décisions ouvertes, dans l'ordre RENDU PAR LE STORE (urgency croissante — 0 est
    le plus urgent — puis `asked_at` croissant : à urgence égale, la plus vieille d'abord).

    Le board ne re-trie pas : l'index `decisions_open` porte déjà cet ordre, et deux tris
    concurrents finiraient par divergerdès qu'un critère change d'un côté seulement.
    Chaque carte gagne `waiting_s`, parce qu'une attente de 27 jours ne se lit pas dans
    un horodatage ISO. `.get` et pas `[...]` : une carte SANS horodatage sort avec une
    ancienneté inconnue, elle ne fait pas tomber la page entière."""
    return [{**carte, "waiting_s": _waiting_s(carte.get("asked_at"))}
            for carte in decisions_service.open_decisions(limit=200)]


def _ticket_index() -> dict[tuple[str, str], dict]:
    """(slug, ticket_id) → ticket, archivés EXCLUS. Une seule requête (`all_tickets`, ~6 ms)."""
    return {(slug, str(ticket.get("id"))): ticket
            for slug, ticket in _persistence.all_tickets()
            if not ticket.get("archived")}


def _linked(task_id: str, links: list[dict], index: dict[tuple[str, str], dict]) -> list[dict]:
    linked = []
    for link in links:
        if link["task_id"] != task_id:
            continue
        ticket = index.get((link["slug"], str(link["ticket_id"])))
        status = derive_status(ticket) if ticket else "introuvable"
        linked.append({"slug": link["slug"], "id": link["ticket_id"],
                       "role": link["role"], "status": status,
                       "title": (ticket or {}).get("title", "")})
    return linked


#  Au-delà de ce délai sans le moindre évènement, une tâche « en cours » ne tourne PLUS : elle est
#  figée. Mesuré le 2026-09-07 : le board annonçait « Ça tourne (1) » pour une tâche dont le dernier
#  évènement avait ONZE JOURS. Un compteur qui ment est un compteur qu'on n'ouvre plus.
STALE_AFTER_S = 1800


def _age_seconds(last_event: dict, now: datetime | None = None) -> int | None:
    """Âge du dernier évènement d'une tâche, en secondes. `None` quand il n'y en a aucun.

    Fonction PURE (`now` injectable) : c'est ce qui rend la règle de fraîcheur testable sans
    attendre 30 minutes, et sans navigateur."""
    age = age_s((last_event or {}).get("at"), now)
    return None if age is None else max(0, int(age))


def _est_arbitrage(task: dict, linked: list[dict]) -> bool:
    """Une tâche à moi, ouverte, sans dépôt ni ticket mais avec un pourquoi écrit : personne ne
    peut l'EXÉCUTER, c'est un arbitrage humain (« À décider »), pas une file de travail."""
    if task["owner"] != "moi" or task["closed_at"] or linked:
        return False
    return not (task["project_slug"] or "").strip() and bool((task["intent"] or "").strip())


def _render_task(task: dict, links, index, events: dict, par_tache: dict) -> dict:
    linked = _linked(task["id"], links, index)
    derived = derive_task_state([ticket["status"] for ticket in linked])
    # `owner='moi'` : l'état est SAISI, pas dérivé — l'écraser effacerait la saisie.
    agent_owned = task["owner"] == "agent" and not task["closed_at"]
    state = derived if agent_owned else task["state"]
    last_event = events.get(task["id"]) or {}
    age_s = _age_seconds(last_event)
    champs = ("id", "title", "owner", "policy", "project_slug", "next_step", "intent",
              "note_anchor", "closed_at", "outcome")
    return {
        **{champ: task[champ] for champ in champs}, "state": state,
        # `fait` est PROPOSÉ : la tâche reste ouverte jusqu'à une clôture humaine.
        "proposed_done": bool(agent_owned and derived == "fait"),
        "last_event": last_event, "age_s": age_s,
        # `stale` ne concerne QUE `en_cours` : un « en cours » muet depuis 30 min ment.
        "stale": bool(state == "en_cours" and age_s is not None and age_s > STALE_AFTER_S),
        "tickets": linked, "open_decisions": par_tache.get(task["id"], 0),
        "arbitrage": _est_arbitrage(task, linked),
    }


def _counts(rendered: list[dict], cartes: list[dict]) -> dict:
    """Compteurs du board. Exposés ici plutôt que recalculés en JS : une règle métier ne se
    re-dérive pas côté front. Les figées ont leur propre compteur : un travail planté doit
    sauter aux yeux, jamais s'effacer de « ça tourne »."""
    counts = {state: sum(1 for task in rendered if task["state"] == state) for state in STATES}
    counts["decisions"] = len(cartes)
    counts["a_faire_travail"] = sum(
        1 for task in rendered if task["state"] == "a_faire" and not task["arbitrage"])
    counts["arbitrages"] = sum(1 for task in rendered if task["arbitrage"])
    counts["figees"] = sum(1 for task in rendered if task["stale"])
    counts["en_cours"] = sum(
        1 for task in rendered if task["state"] == "en_cours" and not task["stale"])
    return counts


def build_board(include_closed: bool = False) -> dict:
    """Payload de `GET /api/board`, version L0 : les tâches, leurs tickets, leurs états.

    `decisions` porte l'ACTE RESTANT : ce que le board attend de moi, pas ce qu'il n'a pas
    regardé. Zéro appel git et zéro LLM ici — les cartes sont lues dans la table alimentée
    au tick (`decision_ingest`), pour tenir les 300 ms p95 du §11."""
    index = _ticket_index()
    links = tasks_service.all_links()
    events = tasks_service.last_event_by_task()
    cartes = _cards()
    # UNE requête d'agrégat pour toutes les tâches (une par tâche rendrait le board quadratique).
    par_tache = decisions_service.count_open_by_task()
    rendered = [_render_task(task, links, index, events, par_tache)
                for task in tasks_service.list_tasks(include_closed=include_closed)]
    return {
        "generated_at": maintenant_iso(),
        "counts": _counts(rendered, cartes), "decisions": cartes, "tasks": rendered,
        "anomalies": [],
    }
