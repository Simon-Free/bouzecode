# [desc] Lecture de l'appel `Agent` commune à ses chemins : pause ou fond, refus d'un profil générique par un manager, refus hors process sous point de contrôle. [/desc]
"""Ce que les chemins de l'outil `Agent` (ticket web, fenêtre de terminal, thread, TUI en
process) lisent tous de la même façon dans l'appel et dans la config du parent."""
from __future__ import annotations

from ..core.tool_registry import TOOL_GATE_KEY


# ── Role-based spawn guard ─────────────────────────────────────────────────

# The manager is a read-only dispatcher: it must characterize a SPECIALIZED
# typology for each ticket, never fall back to a generic un-scoped agent.
# Spawning 'general-purpose' or 'default' from a manager defeats that purpose.
_MANAGER_FORBIDDEN_TYPES = {"general-purpose", "default"}


def _manager_type_guard(config: dict, subagent_type: str) -> str | None:
    """Return a refusal message if the CURRENT profile is 'manager' and it tries
    to spawn a generic un-specialized agent; otherwise None (allowed).

    Pure function (config in, message out) — testable without any mock/patch.
    """
    if config.get("_agent_type") != "manager":
        return None
    if (subagent_type or "").strip().lower() not in _MANAGER_FORBIDDEN_TYPES:
        return None
    return (
        f"Refused: a manager cannot spawn subagent_type "
        f"'{subagent_type}'. The manager must characterize a SPECIALIZED "
        "typology for each ticket (e.g. coder, frontend, meta-agent) — "
        "never the generic 'general-purpose' or 'default' agent. "
        "Use ListAgentTypes to pick a specialized type."
    )


def _attend_l_enfant(params: dict) -> bool:
    """Le parent se met-il en PAUSE jusqu'à la fin de l'enfant ? Une seule lecture de l'option
    pour les TROIS chemins (ticket web, fenêtre de terminal, thread en process).

    `background=true` rend la main ; défaut = pause (sémantique de Bash). `wait`, l'ancien nom
    inverse, prime s'il est fourni. Jusqu'au 2026-09-25 seuls les tickets web lisaient
    `background` : en terminal et en process, `background=true` — l'option que le schéma
    documente — était IGNORÉ et le parent attendait quand même chaque enfant."""
    if "wait" in params:
        return bool(params["wait"])
    return not bool(params.get("background", False))


def _gate_hors_process(config: dict) -> str | None:
    """Refus explicite : un sous-agent dans un AUTRE process ne peut pas emporter le point
    de contrôle de l'hôte (un callable), il échapperait donc au contrôle."""
    if config.get(TOOL_GATE_KEY) is None:
        return None
    return ("Error: sous-agent hors process (fenêtre de terminal / ticket web) refusé : "
            f"l'application hôte a posé un point de contrôle des outils (config['{TOOL_GATE_KEY}']) "
            "qui ne peut pas suivre dans un autre process. Poursuis sans sous-agent.")
