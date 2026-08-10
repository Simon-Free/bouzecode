"""Classification des conversations listées dans l'onglet Conversations.

Quatre natures mutuellement exclusives, dérivées des métadonnées de l'agent
(pas d'appel LLM) :

  - ``test``     : titre/prompt commençant par le mot "test" (heuristique purge).
  - ``meta``     : lancée par le méta-agent (dispatcher). parent == "dispatcher:manual".
  - ``subagent`` : sous-agent d'un manager. parent == un agent_id (non vide, non dispatcher).
  - ``user``     : lancée directement par l'utilisateur hors manager. parent == "".

Priorité : test > meta > subagent > user (une conv de test reste "test" même si
elle a un parent).
"""
from __future__ import annotations

from ...runtime import runner
from . import purge

CATEGORY_TEST = "test"
CATEGORY_META = "meta"
CATEGORY_SUBAGENT = "subagent"
CATEGORY_USER = "user"

_DISPATCHER_PARENT = "dispatcher:manual"


def classify_agent(agent: runner.Agent) -> str:
    """Nature d'une conversation agent web. Voir docstring module pour la priorité."""
    title = (agent.prompt or "").strip().split("\n")[0][:90] or agent.agent_id
    if purge.is_test_agent(title, agent.prompt or ""):
        return CATEGORY_TEST
    parent = (agent.parent or "").strip()
    if not parent:
        return CATEGORY_USER
    if parent == _DISPATCHER_PARENT:
        return CATEGORY_META
    return CATEGORY_SUBAGENT
