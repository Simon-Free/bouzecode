# [desc] Interrompre le tour d'un agent : demande douce (cancel.flag), puis escalade bornée (mise à mort estampillée) s'il ne cède pas. Source unique pour la route …/interruptions, la transmission « interrompre » et l'arrêt d'une tâche. [/desc]
"""Interruption d'un agent en plein tour.

Extrait des routes de sessions pour que la route `…/interruptions` et la transmission d'un message
en mode « interrompre » (`file_messages.transmettre`) suivent EXACTEMENT le même geste.
"""
from __future__ import annotations

import time

from ...runtime import ipc
from ...runtime.runner import agent_arret, agent_chaud

INTERRUPT_REFUSED = (
    "⛔ Interruption REFUSÉE par l'OS pour l'agent `{agent_id}` : {error}. Le process est "
    "peut-être déjà en train de mourir, ou son pid appartient à une autre session. L'agent "
    "n'a PAS été arrêté — réessaie, ou vérifie son process avant de relancer le ticket."
)


def stamp_before_kill(agent, status: str, origin: str):
    """Écrit dans l'IPC la VÉRITÉ (« c'est le serveur qui m'a arrêté ») AVANT la mise à
    mort, et rend la closure de ROLLBACK à appeler si la mise à mort échoue.

    Un agent ne peut pas écrire « je suis mort » : tué, il meurt avant d'avoir pu corriger
    son `state.json`, qui reste figé sur `running` avec un pid périmé. L'observateur croise
    « l'IPC dit running » + « le process n'existe plus » et crie à la mort en plein tour —
    alors que c'est l'état transitoire d'une relance normale (4 alertes le 2026-08-25, 4
    faux positifs). Le serveur, LUI, sait qu'il va tuer : il l'inscrit donc d'abord.

    L'ordre importe : estampiller APRÈS laisserait la fenêtre de contradiction ouverte
    pendant toute la mise à mort. Et si l'OS REFUSE de tuer (`AccessDenied`), l'état
    d'avant est remis tel quel : un agent marqué mort qui tourne toujours est le mensonge
    INVERSE, bien pire, car la supervision cesse de le regarder."""
    ipc_dir = getattr(agent, "ipc_dir", "") or ""
    if not ipc_dir:
        return lambda: None
    paths = ipc.from_dir(ipc_dir)
    existait = paths.state.exists()
    avant = ipc.read_state(paths) if existait else {}
    ipc.write_state(paths, status, killed_by="server", origin=origin,
                    pid=getattr(agent, "pid", None))

    def rollback() -> None:
        if not existait:
            # Il n'y avait AUCUN état : ne pas laisser derrière soi une estampille qui
            # annonce une mort qui n'a pas eu lieu.
            paths.state.unlink(missing_ok=True)
            return
        extras = {k: v for k, v in avant.items() if k not in ("status", "updated_at")}
        ipc.write_state(paths, avant.get("status", ipc.STATUS_RUNNING), **extras)

    return rollback


def _a_cede(agent) -> bool:
    """L'agent a-t-il lâché son tour ? Il ne le tient plus, OU il a CONSOMMÉ la demande.

    Le second critère compte depuis que l'agent repart seul avec les messages en attente :
    une interruption réussie le fait retomber oisif puis REPARTIR aussitôt (nouveau tour,
    avec le message). Juger sur « tient-il un tour ? » seul tuait ce nouveau tour."""
    paths = ipc.from_dir(agent.ipc_dir) if getattr(agent, "ipc_dir", "") else None
    return not agent_chaud.is_mid_turn(agent) or (paths is not None and not paths.cancel.exists())


def _signaler_refus(agent, error: str) -> None:
    """Rend l'échec VISIBLE là où l'utilisateur regarde : sur le ticket de l'agent (il est
    déjà inscrit sur l'agent par `runner.signal_termination`). Sans ticket rattaché, le
    champ de l'agent reste le seul témoin — c'est le cas des conversations hors ticket."""
    from . import tickets
    slug = getattr(agent, "ticket_slug", "") or ""
    ticket_id = getattr(agent, "ticket_id", "") or ""
    ticket = tickets.get_ticket(slug, ticket_id) if slug and ticket_id else None
    if ticket is not None:
        tickets.add_comment(slug, ticket, INTERRUPT_REFUSED.format(
            agent_id=agent.agent_id, error=error), True)


def interrompre(agent, grace_s: float = 1.5) -> dict:
    """Interruption d'abord DOUCE (cancel.flag), puis ESCALADE si l'agent ne cède pas.

    Le tour en cours s'arrête proprement au prochain point d'interruption (streaming LLM
    sondé toutes les 0,2 s, frontières du lot d'outils) ; l'agent garde ses résultats d'outils
    et sa note, et son process reste chaud. S'il tient toujours son tour après la grâce, son
    process est TUÉ (estampillé `interrupted_by_server` : session intacte, reprise à froid).

    Rend `{ok, escalated}` ; un refus de l'OS est un RÉSULTAT (`ok: False` + `error`)."""
    agent_arret.graceful_cancel_agent(agent)
    for _ in range(max(int(grace_s / 0.5), 1)):
        if _a_cede(agent):
            break
        time.sleep(0.5)
    if _a_cede(agent):
        return {"ok": True, "escalated": False}
    rollback = stamp_before_kill(agent, ipc.STATUS_INTERRUPTED_BY_SERVER, "interrupt")
    outcome = agent_arret.kill_agent(agent)
    if outcome.get("error"):
        rollback()
        _signaler_refus(agent, outcome["error"])
        return {"ok": False, "escalated": True, "error": outcome["error"]}
    return {"ok": True, "escalated": True}
