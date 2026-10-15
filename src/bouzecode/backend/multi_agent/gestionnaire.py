# [desc] Singleton de process du SubAgentManager (sous-agents en thread et en terminal). [/desc]
"""Le gestionnaire des sous-agents locaux, unique par process.

Les appelants l'importent DANS leurs fonctions (`from .gestionnaire import get_agent_manager`) :
la résolution a lieu à l'appel, donc un test qui remplace `gestionnaire.get_agent_manager`
atteint tous les chemins.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .manager import SubAgentManager

_agent_manager: SubAgentManager | None = None


def get_agent_manager() -> "SubAgentManager":
    """Return (and lazily create) the process-wide SubAgentManager."""
    global _agent_manager
    if _agent_manager is None:
        from .manager import SubAgentManager
        _agent_manager = SubAgentManager()
    return _agent_manager
