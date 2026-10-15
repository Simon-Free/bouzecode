# [desc] The default agent must be able to spawn sub-agents (not just the manager). [/desc]
"""L'agent par défaut doit pouvoir déléguer à des sous-agents.

Historique : `Agent`/`MessageAgent`/`ListAgentTypes`/`Fleet` n'étaient pas dans la
whitelist par défaut (`_DEFAULT_WORK_TOOLS`), donc désactivés à l'import. Seul le
profil `manager`, qui déclare une allowlist explicite, les récupérait. Un profil
sans restriction (`tools: []`, cas du `default`) n'obtenait donc RIEN de plus :
« pas de restriction » n'est pas « tout activé ».

Ces tests vérifient le comportement au niveau utilisateur : quels outils l'agent
par défaut a réellement à disposition, et que le manager reste read-only.
"""
import pytest

from bouzecode.backend.tools.registration import enabled_tools_for_profile

SUBAGENT_TOOLS = ["Agent", "MessageAgent", "ListAgentTypes", "Fleet"]


@pytest.mark.parametrize("tool_name", SUBAGENT_TOOLS)
def test_default_profile_can_spawn_subagents(tool_name):
    """Le profil par défaut expose les outils de délégation."""
    assert tool_name in enabled_tools_for_profile("default"), (
        f"{tool_name} manquant pour l'agent par défaut : il ne peut pas déléguer."
    )


def test_default_profile_still_has_code_discovery_and_write_tools():
    """Non-régression : la délégation ne remplace pas les outils de travail."""
    enabled = enabled_tools_for_profile("default")
    for tool_name in ("Read", "Write", "Edit", "Bash", "FindCode", "Tree",
                      "RunPythonTest", "Methodology", "Snippet", "FinalAnswer"):
        assert tool_name in enabled, f"{tool_name} manquant pour l'agent par défaut"


def test_manager_profile_stays_read_only():
    """Le manager déclare une allowlist : elle reste une vraie whitelist."""
    enabled = enabled_tools_for_profile("manager")
    for tool_name in SUBAGENT_TOOLS:
        assert tool_name in enabled, f"{tool_name} manquant pour le manager"
    for forbidden in ("Write", "Edit", "Bash"):
        assert forbidden not in enabled, (
            f"{forbidden} ne doit PAS être exposé au manager (rôle read-only)"
        )
