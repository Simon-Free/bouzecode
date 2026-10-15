# [desc] Cartes « A traiter » des signalements d'agents (outil Signaler) et regle des sous-agents arretes orphelins (aucun parent vivant pour s'en occuper). [/desc]
"""Deux sources de « A traiter » ajoutees a `inbox._construire` :

* les SIGNALEMENTS ouverts, une carte chacun, urgence selon la gravite, avec l'agent, sa
  profondeur, sa chaine de parents, son ticket et sa tache ;
* la regle des sous-agents ARRETES : jusqu'ici « un sous-agent arrete est l'affaire de son
  manager » — vrai seulement si ce manager est encore la. Un sous-agent dont le parent est
  introuvable, lui-meme arrete, ou un assistant de terminal (`tui:`, jamais reveille
  automatiquement) n'avait personne : il apparait desormais dans la boite.
"""
from __future__ import annotations

from . import signalements


def _tache(ticket_id: str, par_ticket: dict[str, dict]) -> dict | None:
    lien = par_ticket.get(ticket_id or "")
    if not lien:
        return None
    return {"micro_id": lien["micro_id"], "titre": lien["titre"],
            "macro_id": lien.get("macro_id", ""), "chantier": ""}


def cartes(par_ticket: dict[str, dict]) -> list[dict]:
    """Une carte par signalement ouvert."""
    return [{"type": "signalement", "id": f"signalement:{s['id']}", "signalement_id": s["id"],
             "titre": s["titre"], "detail": s["detail"], "gravite": s["gravite"],
             "action_attendue": s["action_attendue"], "raison": s["detail"],
             "urgence": signalements.URGENCE.get(s["gravite"], 2),
             "motif": "signalement_bloquant" if s["gravite"] == "bloquant" else "signalement",
             "agent_id": s["agent_id"], "key": f"agent/{s['agent_id']}" if s["agent_id"] else "",
             "depuis": s["created_at"], "profondeur": s["profondeur"], "parents": s["parents"],
             "ticket_id": s["ticket_id"], "projet_slug": s["ticket_slug"],
             "tache": _tache(s["ticket_id"], par_ticket),
             "actions": ["acquitter", "ouvrir"]} for s in signalements.ouverts()]


def parent_peut_s_en_occuper(parent: str, noeuds_par_id: dict[str, dict]) -> bool:
    """Le parent existe dans le parc et n'est pas lui-meme arrete : son reveil lui portera
    l'arret de l'enfant (`wake`). Sinon personne d'autre que l'humain ne le verra."""
    noeud = noeuds_par_id.get(str(parent or ""))
    return noeud is not None and not noeud.get("interrupted")
