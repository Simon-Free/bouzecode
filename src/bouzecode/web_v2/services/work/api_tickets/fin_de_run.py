# [desc] Fin d'un run annoncée par le hook de l'agent (POST /internal/runs/{agent_id}/ended) : jeton propre au run vérifié, run du ticket vérifié, issue décidée par close_reasons. [/desc]
"""Spec §6.5. Le hook `run_completion_chain` de l'agent annonce sa fin ; `close_reasons` décide
SEUL de l'issue (`delivered`, `idle_no_delivery`, `stopped`) et `constats.fin_de_run` applique la
transition. Aucune suite automatique. Un hook qui arrive après que le watchdog a classé le run
`stopped{crashed}` corrige l'état s'il prouve une réponse finale.

Contrôles (constat C12) : ticket inconnu ou archivé → 404 ; agent qui n'est pas un run de CE
ticket → 404 ; sur la route interne, jeton du run absent ou faux → 403 `jeton_run_invalide`."""
from __future__ import annotations

import hmac

from ....runtime.runner import agent_fiche
from .. import constats, reaper, tickets
from .refus import Refus

EN_TETE_RUN = "X-Bouzecode-Run-Token"


def verifier_le_jeton(agent_id: str, recu: str):
    """L'agent du run, si `recu` est SON jeton ; sinon `Refus` (404 inconnu, 403 jeton)."""
    agent = agent_fiche.load_agent(agent_id)
    if agent is None or not agent.ticket_id:
        raise Refus("run_inconnu", f"run inconnu : {agent_id}", 404, agent_id=agent_id)
    attendu = getattr(agent, "run_token", "") or ""
    if not (attendu and recu and hmac.compare_digest(recu, attendu)):
        raise Refus("jeton_run_invalide", f"en-tête {EN_TETE_RUN} absent ou faux pour ce run",
                    403, agent_id=agent_id)
    return agent


def terminer(slug: str, ticket_id: str, agent_id: str, close_reason: str) -> dict:
    ticket = tickets.get_ticket(slug, ticket_id)
    if ticket is None or ticket.get("archived"):
        raise Refus("ticket_inconnu", f"ticket inconnu : {ticket_id}", 404, ticket_id=ticket_id)
    runs = {r.get("agent_id") for r in ticket.get("runs") or [] if isinstance(r, dict)}
    if agent_id and agent_id not in runs:
        raise Refus("run_inconnu", f"l'agent {agent_id} n'est pas un run du ticket {ticket_id}",
                    404, agent_id=agent_id, ticket_id=ticket_id)
    if close_reason == "final_answer_deferred":  # des vérifications différées restent à drainer
        return {"ok": True, "advanced_to": None, "deferred": True, "state": ticket.get("state")}
    agent_id = agent_id or str(next((r.get("agent_id") for r in ticket.get("runs") or []), ""))
    nouvel_etat = constats.fin_de_run(slug, ticket_id, agent_id, close_reason)
    frais = tickets.get_ticket(slug, ticket_id) or ticket
    reaper.reap_ticket(slug, frais)  # fauche aussitôt un ticket que ce passage a rendu intégré
    reponse = {"ok": True, "advanced_to": nouvel_etat, "state": frais.get("state"),
               "state_reason": frais.get("state_reason")}
    if close_reason == "api_error":
        reponse["api_error"] = True
    return reponse
