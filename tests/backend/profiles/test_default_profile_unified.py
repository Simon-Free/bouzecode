"""The `default` profile is THE unified code agent — shipped with bouzecode.

User-facing contract exercised here: whatever the project, an agent running WITHOUT an
explicit profile receives (a) the code-discovery ladder led by FindCode, (b) the prose formerly locked inside the `coder` profile, and (c) the
sub-agent dispatch prose formerly locked inside the `manager` profile — plus the tools
to actually dispatch.

These assertions read the real composed prompt through the public entry point used by
dispatch.py (`get_agent_profile_extra`), not the YAML file directly.
"""

from bouzecode.backend.core.profile_extra import (
    _DEFAULT_PROFILE_EXTRA_CACHE,
    get_agent_profile_extra,
)
from bouzecode.backend.profiles import load_system_profiles


def _default_prose() -> str:
    _DEFAULT_PROFILE_EXTRA_CACHE.clear()
    return get_agent_profile_extra("default")


def test_default_profile_is_shipped_with_bouzecode():
    """A fresh project with no .bouzecode/profiles must still get the default prose."""
    assert "default" in load_system_profiles()


def test_default_prose_puts_findcode_first():
    prose = _default_prose()
    assert "`FindCode` d'abord" in prose


def test_default_prose_carries_the_coder_layer():
    prose = _default_prose()
    for marker in (
        "RunPythonTest",
        "unittest.mock",
        "Fixtures copiées du réel",
        "## 1. Résumé",
        "## 6. Nouveaux tests / corrections",
        "`recap`",
    ):
        assert marker in prose, marker


def test_default_prose_carries_the_manager_dispatch_layer(monkeypatch):
    #  `MessageAgent` est dans un bloc `<!-- si:flotte -->` : prose vue quand une flotte
    #  existe (web, ou TUI qui héberge ses sous-agents) — le cas où le profil délègue.
    from bouzecode.backend.core import tool_registry
    monkeypatch.setattr(tool_registry, "_flotte_locale", True)
    prose = _default_prose()
    for marker in (
        "subagent_type",
        "ListAgentTypes",
        "MessageAgent",
        "work_branch",
        "jamais d'intégration déléguée",
    ):
        assert marker in prose, marker
    # Audit du prompt (2026-09-24) : `isolation=` / `worktree+venv` n'existent plus sur
    # l'outil Agent (l'enfant demande son environnement lui-même) ; l'anti-churn (« plus rien
    # à lancer → FinalAnswer d'avancement ») vit dans le noyau, pour tout agent qui délègue.
    assert "worktree+venv" not in prose
    assert "isolation=" not in prose


def test_default_prose_does_not_forbid_writing_code():
    """The manager's read-only interdicts must NOT have been copied over."""
    prose = _default_prose()
    assert "Interdit absolu" not in prose
    assert "Tu n'écris ni code ni tests" not in prose


def test_default_profile_grants_every_tool():
    """Empty allowlist == no restriction; a listed allowlist is what starved `coder`."""
    profile = load_system_profiles()["default"]
    assert list(profile.tools) == []


def test_default_profile_requires_recap():
    assert load_system_profiles()["default"].require_recap is True
