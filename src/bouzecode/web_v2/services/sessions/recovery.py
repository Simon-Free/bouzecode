# [desc] Liste et relance manuellement les conversations interrompues (process mort sans FinalAnswer). [/desc]
"""Une conversation est « interrompue » quand son process est mort (state finished,
car refresh_agent_status force returncode=0 dès la mort du process) SANS avoir émis
de FinalAnswer (close_reason != "final_answer"). On NE relance PAS automatiquement :
on les liste (GET /api/agents?state=interrupted) pour une reprise MANUELLE par un message
(POST /api/agents/<id>/messages).

Les fins PROPRES (close_reason == "final_answer") sont exclues d'ici : le watchdog les
réconcilie depuis la session disque, sans dépendre d'un callback réseau."""
from __future__ import annotations

from ... import close_reasons
from ...runtime.runner import agent_creation, agent_fiche
from . import store

def is_interrupted(agent_item: dict) -> bool:
    """Vrai si l'agent est mort sans fin propre (aucune livraison sur disque).

    Le test portait sur UNE chaîne : `close_reason != "final_answer"`. Or plusieurs
    clôtures prouvent une livraison, et `close_reasons.py` les recense déjà dans
    `DELIVERY_CLOSE_REASONS` (`proves_delivery=True`). Comparer à une seule valeur
    littérale, c'est se fabriquer un critère plus étroit que celui du gateway — et
    déclarer « interrompu » un agent qui a livré.

    Mesuré le 2026-08-24 : `ba7590f4a760` (20/07, 36 tours, `returncode=0`, réponse
    finale de 6 152 caractères, correctifs fusionnés dans `develop` en `90c5825` et
    `f6f773b`, branche et worktree rangés) sortait ici comme interrompu, un mois
    après sa livraison, au seul motif que sa clôture était `final_answer_deferred`
    — que `close_reasons.py` déclare pourtant `_DELIVERED`.

    C'était la troisième vue à se donner sa propre définition de « planté » plutôt
    que celle du gateway ; les deux autres (le bandeau de boot, le snapshot figé)
    affichaient le même faux positif sur d'autres chemins.
    """
    finished = agent_item.get("status", {}).get("state") == "finished"
    livre = agent_item.get("close_reason") in close_reasons.DELIVERY_CLOSE_REASONS
    return finished and not livre


def list_interrupted() -> list[dict]:
    """Conversations interrompues par crash/restart, à relancer manuellement.

    `list_agent_sessions` et non `list_sessions` : seule la clé "agents" était lue, mais
    `list_sessions` balaie EN PLUS les sessions CLI des 10 derniers jours — 281 fichiers,
    597 Mo sur le poste — pour jeter le résultat aussitôt."""
    interrupted = []
    for agent in store.list_agent_sessions():
        if not is_interrupted(agent):
            continue
        key = agent["key"]
        interrupted.append({
            "key": key,
            "agent_id": key.split("/", 1)[1] if "/" in key else key,
            "title": agent.get("title", ""),
            "cwd": agent.get("cwd", ""),
            "close_reason": agent.get("close_reason", ""),
            "started_at": agent.get("started_at", ""),
            "saved_at": agent.get("saved_at", ""),
            "model": agent.get("model", ""),
        })
    return interrupted


def relaunch(agent_id: str, prompt: str) -> str | None:
    """Relance manuellement une conversation interrompue en reprenant sa session.
    Retourne le nouvel agent_id, ou None si l'agent est inconnu."""
    agent = agent_fiche.load_agent(agent_id)
    if agent is None:
        return None
    # Comme /continue et messaging : re-home AVANT de resumer. Sans ça, un agent dont le worktree
    # a été fauché (merge+reap) repart dans un dossier vide et se bloque « worktree vide ». Pour un
    # agent À TICKET, rehome re-provisionne un worktree neuf off la branche vive ; pour un
    # sous-agent SANS ticket, _safe_cwd (runner) rabat sur le checkout serveur au spawn.
    from ..work import dispatch
    dispatch.rehome_agent_cwd(agent)
    new_agent = agent_creation.resume_agent(agent, prompt)
    return new_agent.agent_id
