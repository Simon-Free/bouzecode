# [desc] Lecture RÉELLE du parc pour la page TO-DO : tickets clos, sessions mémoïsées, conversations de test. [/desc]
"""La source live de la page TO-DO et ses trois lectures de ticket.

Extraites de l'ancien digest TODO du pont Teams (retiré : l'écriture dans Teams est
obsolète). Ce qui reste ne parle pas à Teams : tickets de tous les projets, session
d'un agent lue une fois par processus (`session_cache`), exclusion des conversations
de TEST, réponse finale.
"""

from __future__ import annotations

from datetime import datetime

from bouzecode.web_v2.services.horodatage import lire_instant


def _closed(ticket: dict) -> bool:
    """Clos AVEC SUCCÈS (`closed` : intégré ou accepté) — un abandon n'a rien à lire."""
    return ticket.get("state") == "closed"


def _created(ticket: dict) -> datetime | None:
    """Instant de création, UTC conscient (`horodatage.lire_instant` : naïf hérité = local)."""
    return lire_instant(ticket.get("created_at"))


def _agent_id(ticket: dict) -> str:
    #  `add_run` insère en tête : runs[0] est le run le PLUS RÉCENT.
    for run in ticket.get("runs") or []:
        agent = str((run or {}).get("agent_id") or "").strip()
        if agent:
            return agent
    return ""


class LiveSource:
    """La vraie lecture du parc. Construite à la demande."""

    def __init__(self):
        self._sessions: dict[str, dict] = {}

    def tickets(self) -> list[dict]:
        from . import projects as projects_service
        from . import tickets as tickets_service

        tous: list[dict] = []
        for projet in projects_service.list_projects() or []:
            slug = str(projet.get("slug") or "").strip()
            if not slug:
                continue
            for ticket in tickets_service.list_tickets(slug, refresh=False,
                                                       persist=False):
                enrichi = dict(ticket)
                enrichi["slug"] = slug
                tous.append(enrichi)
        return tous

    def _session(self, agent_id: str) -> dict:
        #  La mémoire vit dans le PROCESSUS (`session_cache`), pas dans l'instance :
        #  la route fabrique une source neuve à chaque requête, et ce cache jeté
        #  avec la réponse coûtait ~600 ms à chaque clic de filtre.
        if agent_id in self._sessions:
            return self._sessions[agent_id]
        from . import session_cache

        session = session_cache.charger(agent_id)
        self._sessions[agent_id] = session
        return session

    def recap(self, agent_id: str) -> dict | None:
        recap = self._session(agent_id).get("recap")
        return recap if isinstance(recap, dict) else None

    def is_test(self, agent_id: str) -> bool:
        """Vrai pour une conversation de TEST (PING/PONG, « Ticket normal »…).

        Même geste que `awaiting.agents_awaiting_answer` : ces conversations gonflent
        le compteur sans porter aucune décision, elles n'ont rien à faire ici.

        Mémoïsé au niveau du processus : c'était une seconde lecture disque par
        ticket clos, sur le chemin critique de `todo_board.collect`."""
        from . import session_cache

        return session_cache.est_test(agent_id)

    def final_answer(self, agent_id: str) -> str:
        from . import tickets as tickets_service

        messages = self._session(agent_id).get("messages")
        if not isinstance(messages, list):
            return ""
        return str(tickets_service.extract_final_answer(messages) or "")
