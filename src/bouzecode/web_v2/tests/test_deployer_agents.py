"""Tests for the two specialized deployer system agents (databricks-deployer,
azure-deployer): each profile resolves with its skills+tools, each deploy skill is
registered and injectable by name, and both new typologies are dispatchable
(appear in list_typologies). No unittest.mock — real registry + real loaders."""
from __future__ import annotations

import pytest


@pytest.mark.parametrize(
    "profile_name, skill_name",
    [
        ("databricks-deployer", "databricks-deploy"),
        ("azure-deployer", "azure-deploy"),
    ],
)
def test_deployer_profile_resolves(profile_name: str, skill_name: str) -> None:
    from bouzecode.backend.profiles import resolve_agent_profile

    profile = resolve_agent_profile(profile_name)
    assert profile is not None, f"{profile_name} did not resolve"
    assert profile.kind == "system", f"{profile_name} must be a system agent"
    # Inherits demo-coding AND carries its own deploy skill.
    assert "demo-coding" in profile.skills
    assert skill_name in profile.skills
    # Même équipement que le codeur (cf. coder.yaml) : code, tests, et délégation.
    for tool in ("Read", "Write", "Edit", "Bash", "RunPythonTest", "FinalAnswer", "Agent"):
        assert tool in profile.tools, f"{tool} missing from {profile_name} tools"


@pytest.mark.parametrize(
    "skill_name, must_contain",
    [
        ("databricks-deploy", ("dbk", "default", "dbfs", "demo")),
        ("azure-deploy", ("deploy.py", "Artifactory", "wwwroot", "BROWSER_PATH")),
    ],
)
def test_deploy_skill_registered_and_injectable(
    skill_name: str, must_contain: tuple[str, ...]
) -> None:
    from bouzecode.backend.tools.skill.loader import load_skills
    from bouzecode.backend.core.context import render_profile_skills

    names = {s.name for s in load_skills()}
    assert skill_name in names, f"{skill_name} not registered"
    # Profile-skill preload path (render_profile_skills) surfaces its content by name.
    rendered = render_profile_skills([skill_name])
    assert skill_name in rendered
    for token in must_contain:
        assert token in rendered, f"'{token}' missing from rendered {skill_name}"


def test_deployer_typologies_are_dispatchable() -> None:
    # list_typologies is the manager's source of truth for what it can dispatch.
    from bouzecode.web_v2.services.typologies import list_typologies

    names = {t["name"] for t in list_typologies()}
    assert "databricks-deployer" in names
    assert "azure-deployer" in names
