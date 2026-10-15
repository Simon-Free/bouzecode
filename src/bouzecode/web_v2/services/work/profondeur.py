# [desc] Profondeur et chaine de parents d'un agent web, calculees en remontant `agent.parent` (sentinelles dispatcher et TUI comprises). [/desc]
"""Ou se situe un agent dans l'arbre des sous-agents.

`chaine_parents(agent_id)` : ses ancetres, du parent direct a la racine. Un parent
`dispatcher:*` (lancement depuis l'ecran) n'en est pas un ; un parent `tui:<id>` (assistant
lance dans le terminal) en est un, mais sans fiche d'agent : la remontee s'arrete a lui,
comme a tout parent inconnu (purge). La profondeur est la longueur de cette chaine : le
runner la passe a l'agent (`BOUZECODE_AGENT_DEPTH`) pour que l'outil `Agent` borne la
recursion (`backend/multi_agent/profondeur.py`).
"""
from __future__ import annotations

ANCETRES_MAX = 50
PREFIXE_TUI = "tui:"


def est_parent_reel(parent: str) -> bool:
    return bool(parent) and not str(parent).startswith("dispatcher:")


def _parent_de(agent_id: str) -> str:
    from ...runtime.runner import agent_fiche
    if agent_id.startswith(PREFIXE_TUI):
        return ""
    agent = agent_fiche.load_agent(agent_id)
    return str(getattr(agent, "parent", "") or "") if agent is not None else ""


def chaine_depuis(parent: str) -> list[str]:
    """Les ancetres a partir d'un parent direct connu (sans relire l'agent lui-meme)."""
    chaine: list[str] = []
    while est_parent_reel(parent) and parent not in chaine and len(chaine) < ANCETRES_MAX:
        chaine.append(parent)
        parent = _parent_de(parent)
    return chaine


def chaine_parents(agent_id: str) -> list[str]:
    return chaine_depuis(_parent_de(str(agent_id or "")))


def profondeur_agent(agent) -> int:
    """Profondeur d'un agent du runner : 0 pour une racine."""
    return len(chaine_depuis(str(getattr(agent, "parent", "") or "")))
