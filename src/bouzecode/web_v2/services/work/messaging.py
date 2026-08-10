# [desc] Ré-instruire un agent enfant existant : résolution ticket_id → (slug, ticket) + continuation. [/desc]
"""Envoi d'une nouvelle instruction à un agent DÉJÀ lancé, identifié par son ticket_id.

Le manager ne connaît de ses enfants que leur ticket_id (cf. wake.build_wake_digest).
`resolve_ticket` retrouve le projet porteur ; `send_to_ticket_agent` reproduit la
logique de continuation de la route /comments (charge le run 'work', refuse si l'agent
tourne encore, resume/continue selon l'état pending) sans la dupliquer."""
from __future__ import annotations

from typing import Any

from ...runtime import pending, runner
from ..sessions import store
from . import delivery, dispatch, projects, tickets


def resolve_ticket(ticket_id: str) -> tuple[str, dict] | None:
    """Cherche le ticket dans tous les projets ouverts. Renvoie (slug, ticket) au 1er
    match, sinon None."""
    if not ticket_id:
        return None
    for project in projects.list_projects():
        ticket = tickets.get_ticket(project["slug"], ticket_id)
        if ticket is not None:
            return project["slug"], ticket
    return None


def send_to_ticket_agent(slug: str, ticket: dict, text: str) -> dict[str, Any]:
    """Relance l'agent du run 'work' avec `text` (même agent, contexte gardé) puis
    journalise le message en commentaire.

    Renvoie {ok: True} ou {ok: False, error, code, reason}. `reason` est le motif
    MACHINE de l'échec, pour que l'appelant (et le front) sache quoi faire au lieu de
    deviner à partir d'un code HTTP :
      * `no_work_run`   — le ticket n'a aucun run de travail (rien à relancer) ;
      * `agent_missing` — le run existe mais l'enregistrement de l'agent a disparu :
                          il est INJOIGNABLE, le message n'est pas parti, et aucune
                          relance ne le réparera (il faut restaurer sa fiche) ;
      * `running`       — l'agent travaille : interrompre puis réessayer a du sens.
    Ces trois cas partageaient un seul message (« aucun run de travail à relancer ») :
    un envoi vers un agent dont la fiche avait disparu était donc annoncé comme un
    conflit de tour, et le front enchaînait deux minutes d'interruptions inutiles."""
    work_run = next((r for r in ticket["runs"] if r["kind"] == "work"), None)
    if work_run is None:
        return {"ok": False, "error": "aucun run de travail à relancer",
                "code": 409, "reason": "no_work_run"}
    agent = runner.load_agent(work_run["agent_id"])
    if agent is None:
        return {"ok": False, "reason": "agent_missing", "code": 404,
                "error": f"agent {work_run['agent_id']} introuvable : son enregistrement "
                         f"a disparu du parc d'agents. RIEN n'a été envoyé — restaure sa "
                         f"fiche (elle peut être dans web_agents/_trash/) avant de réessayer."}
    if store.agent_status(agent)["state"] == "running":
        return {"ok": False, "error": "l'agent tourne encore — attends la fin du tour",
                "code": 409, "reason": "running"}
    # Follow-up sur un ticket done/mergé/reapé : le worktree a pu être nettoyé. On re-home vers un
    # worktree frais (reisolate off base branch) AVANT le resume, comme /continue — relancer plutôt
    # que refuser (aligné sur dispatch.rehome_agent_cwd / sessions.api_agent_continue).
    dispatch.rehome_agent_cwd(agent)
    # L'agent repart : sa livraison précédente ne vaut plus quitus de récolte, sinon le
    # travail produit à ce nouveau tour ne serait jamais commité (cf. delivery.py).
    delivery.reopen_for_new_work(slug, ticket.get("id", ""))
    if pending.exists(agent.session_path):
        delivered = runner.resume_pending_agent(agent, text)
    else:
        delivered = runner.continue_agent(agent, text)
    # `not_delivered` — `_respawn` a refusé de lancer un jumeau (un process tourne déjà pour
    # cette session) et a rendu None : le message n'est PAS parti. Ce None n'était pas lu, si
    # bien qu'on répondait `ok` et qu'on journalisait un commentaire pour un message que
    # personne n'a reçu. Un envoi perdu doit se dire, jamais se deviner.
    if delivered is None:
        return {"ok": False, "reason": "not_delivered", "code": 409,
                "error": "un process tourne déjà pour cette session : le message n'a PAS été "
                         "transmis. Interromps l'agent puis réessaie."}
    tickets.add_comment(slug, ticket, text, True)
    # L'enfant DOIT désormais une réponse. Sans ce drapeau, entre ce `continue_agent` et le
    # premier tour où son process est observé `running`, l'enfant repasse « terminal » avec
    # l'issue qu'il avait déjà : `wake.process_wakes` y voit « tous les enfants terminaux,
    # signature inchangée » et CLÔTURE le manager qui attend justement cette réponse.
    # `tickets.mark_run_completed` le retire — le tour clos EST la réponse.
    tickets.mark_awaiting_reply(slug, ticket)
    return {"ok": True}
