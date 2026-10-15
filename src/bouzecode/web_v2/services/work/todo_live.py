# [desc] Source de lecture RÉELLE de la page TO-DO : déclarations de clôture + état des agents. [/desc]
"""La vraie lecture du parc pour l'onglet TO-DO.

Hérite de la source déjà éprouvée (`todo_source`) (tickets, récap, exclusion des
conversations de TEST, réponse finale) et n'y AJOUTE que ce que la page réclame :

* `taches(agent_id)` — la déclaration obligatoire de `FinalAnswer`
  (`taches_terminees` / `taches_restantes` / `taches_declarees`), lue telle quelle
  dans le journal de session. Aucun LLM ne relit une réponse pour la devenir :
  ce qui n'est pas déclaré n'existe pas, et se dira « non déclaré ».
* `etat_agent(agent_id)` — « en cours, tour N », déduit du MÊME journal déjà
  chargé : un agent qui n'a pas encore posé sa réponse finale tourne, et son tour
  est le nombre de ses prises de parole. Ni appel git, ni `/api/agents/tree`, ni
  process inspecté : la page doit tenir son budget de 300 ms.
"""
from __future__ import annotations

from .todo_source import LiveSource


class TodoSource(LiveSource):
    """Source live de la page TO-DO (les sessions sont mémoïsées par la classe mère)."""

    def taches(self, agent_id: str) -> dict:
        """Rend la déclaration de clôture, sans rien inventer quand elle manque."""
        session = self._session(agent_id)
        restantes = session.get("taches_restantes")
        terminees = session.get("taches_terminees")
        return {
            "taches_restantes": restantes if isinstance(restantes, list) else None,
            "taches_terminees": terminees if isinstance(terminees, list) else [],
            "taches_declarees": bool(session.get("taches_declarees")),
        }

    def etat_agent(self, agent_id: str) -> dict:
        """Rend `{actif, tour}` : un agent sans réponse finale est encore au travail."""
        if not agent_id:
            return {"actif": False, "tour": 0}
        session = self._session(agent_id)
        messages = session.get("messages")
        tour = 0
        if isinstance(messages, list):
            tour = len([m for m in messages
                        if isinstance(m, dict) and m.get("role") == "assistant"])
        return {"actif": not str(session.get("final_answer") or "").strip(),
                "tour": tour}
