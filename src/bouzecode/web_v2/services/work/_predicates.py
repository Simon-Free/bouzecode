# [desc] Prédicats booléens de lecture d'un ticket (verdict connu, run de travail vivant), ré-exportés par integration. [/desc]
"""Prédicats de lecture de l'état d'un ticket.

Extraits d'`integration.py` (split conformité <200L). Ce module ne fait AUCUNE
action (ne spawn/merge/commit rien) : il répond à des questions sur l'état persisté.
Ré-exportés par `integration` pour compat (`integration.latest_verdict`, etc.)."""
from __future__ import annotations

from ...runtime import runner
from ..sessions import store


def latest_verdict(ticket: dict) -> str | None:
    """Verdict (OK|KO) du run de validation le plus récent, ou None. Le validateur n'est
    plus lancé automatiquement, mais un manager peut toujours en spawner un : son verdict
    reste lisible ici (statut du ticket, digest de réveil du parent)."""
    for run in ticket.get("runs") or []:
        if isinstance(run, dict) and str(run.get("kind", "")).startswith("validate"):
            return run.get("verdict")
    return None


def _work_running(ticket: dict, done_agent: str = "") -> bool:
    """L'agent du run 'work' le plus récent tourne-t-il ? `done_agent` (l'agent dont
    la complétion déclenche l'appel) est traité comme TERMINÉ même si son process
    n'a pas encore quitté — sinon le hook in-process se bloquerait lui-même."""
    work = next((r for r in ticket.get("runs") or [] if r.get("kind") == "work"), None)
    if not work:
        return False
    if work["agent_id"] == done_agent:
        return False
    if work.get("completed"):
        return False  # run fini gracieusement (hook /completed OU reconcile crash-aware) :
                      # un process ZOMBIE qui traîne ne doit PAS bloquer le merge à l'infini.
    agent = runner.load_agent(work["agent_id"])
    return bool(agent and store.agent_status(agent)["state"] == "running")
