# [desc] Liste et relance manuellement les conversations interrompues (process mort sans FinalAnswer). [/desc]
"""Une conversation est « interrompue » quand son process est mort (state finished,
car refresh_agent_status force returncode=0 dès la mort du process) SANS avoir émis
de FinalAnswer (close_reason != "final_answer"). On NE relance PAS automatiquement :
on les liste pour une reprise MANUELLE via relaunch (runner.resume_agent).

Les fins PROPRES (close_reason == "final_answer") sont exclues d'ici : elles sont
auto-réconciliées ailleurs (tickets.refresh_verdicts relève le verdict sur disque
sans dépendre d'un callback réseau)."""
from __future__ import annotations

from ...runtime import runner
from . import store

DEFAULT_RELAUNCH_PROMPT = "Reprends la tâche interrompue là où elle s'est arrêtée."


def is_interrupted(agent_item: dict) -> bool:
    """Vrai si l'agent est mort sans fin propre (pas de FinalAnswer sur disque)."""
    finished = agent_item.get("status", {}).get("state") == "finished"
    return finished and agent_item.get("close_reason") != "final_answer"


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
    agent = runner.load_agent(agent_id)
    if agent is None:
        return None
    # Comme /continue et messaging : re-home AVANT de resumer. Sans ça, un agent dont le worktree
    # a été fauché (merge+reap) repart dans un dossier vide et se bloque « worktree vide ». Pour un
    # agent À TICKET, rehome re-provisionne un worktree neuf off la branche vive ; pour un
    # sous-agent SANS ticket, _safe_cwd (runner) rabat sur le checkout serveur au spawn.
    from ..work import dispatch
    dispatch.rehome_agent_cwd(agent)
    new_agent = runner.resume_agent(agent, prompt)
    return new_agent.agent_id
