"""Tests for the agent profiles system (loading, composition, integration)."""
from pathlib import Path

import pytest

from bouzecode.backend.profiles.models import AgentProfile
from bouzecode.backend.profiles.loader import load_profile_from_path, load_profiles_from_dir
from bouzecode.backend.profiles.composer import merge_profiles, _union_lists


def test_load_profile_from_yaml(tmp_path):
    """Load a single profile YAML and verify all fields parsed correctly."""
    yaml_content = (
        "name: analyst\n"
        "skills:\n  - databricks-tables\n"
        "tools:\n  - Read\n  - Bash\n"
        "hooks:\n  - enforcement\n"
        "model: gpt-4\n"
        "system_prompt_extra: You are a data analyst.\n"
    )
    (tmp_path / "analyst.yaml").write_text(yaml_content, encoding="utf-8")
    profile = load_profile_from_path(tmp_path / "analyst.yaml")
    assert profile.name == "analyst"
    assert profile.skills == ["databricks-tables"]
    assert profile.tools == ["Read", "Bash"]
    assert profile.hooks == ["enforcement"]
    assert profile.model == "gpt-4"
    assert "data analyst" in profile.system_prompt_extra


def test_merge_profiles_union_and_last_wins():
    """Merge two profiles: lists are unioned (ordered, deduplicated), model is last-non-empty-wins."""
    a = AgentProfile(
        name="a",
        skills=["s1", "s2"],
        tools=["Read", "Write"],
        hooks=["h1"],
        model="gpt-4",
        system_prompt_extra="Prompt A.",
    )
    b = AgentProfile(
        name="b",
        skills=["s2", "s3"],
        tools=["Write", "Bash"],
        hooks=["h2"],
        model="claude",
        system_prompt_extra="Prompt B.",
    )
    merged = merge_profiles([a, b])
    assert merged.skills == ["s1", "s2", "s3"]
    assert merged.tools == ["Read", "Write", "Bash"]
    assert merged.hooks == ["h1", "h2"]
    assert merged.model == "claude"  # last non-empty wins
    assert merged.system_prompt_extra == "Prompt A.\n\nPrompt B."


def test_merge_profiles_empty_model_skipped():
    """A profile with empty model doesn't override previous model."""
    a = AgentProfile(name="a", model="gpt-4")
    b = AgentProfile(name="b", model="")
    merged = merge_profiles([a, b])
    assert merged.model == "gpt-4"


def test_merge_empty_profiles():
    """Merging zero profiles returns an empty AgentProfile."""
    merged = merge_profiles([])
    assert merged.skills == []
    assert merged.tools == []
    assert merged.hooks == []
    assert merged.model == ""
    assert merged.system_prompt_extra == ""


def test_union_lists_preserves_order_and_deduplicates():
    """_union_lists keeps first-seen order and removes duplicates."""
    result = _union_lists([["a", "b", "c"], ["b", "d", "a"], ["e"]])
    assert result == ["a", "b", "c", "d", "e"]


def test_agent_definition_with_profiles_resolves(tmp_path):
    """End-to-end: profiles loaded from dir and merged produce correct resolution."""
    (tmp_path / "analyst.yaml").write_text(
        "name: analyst\n"
        "skills:\n  - databricks-tables\n"
        "tools:\n  - Read\n  - Bash\n"
        "hooks: []\n"
        "model: gpt-4\n"
        "system_prompt_extra: Data analyst.\n",
        encoding="utf-8",
    )
    (tmp_path / "secure.yaml").write_text(
        "name: secure\n"
        "skills:\n  - troubleshooting\n"
        "tools:\n  - Read\n"
        "hooks:\n  - enforcement\n"
        'model: ""\n'
        "system_prompt_extra: Security-focused.\n",
        encoding="utf-8",
    )
    profiles = load_profiles_from_dir(tmp_path)
    assert "analyst" in profiles
    assert "secure" in profiles

    resolved = merge_profiles([profiles["analyst"], profiles["secure"]])
    assert resolved.skills == ["databricks-tables", "troubleshooting"]
    assert resolved.tools == ["Read", "Bash"]  # union, deduplicated
    assert resolved.hooks == ["enforcement"]
    assert resolved.model == "gpt-4"  # secure has empty model, analyst's wins
    assert "Data analyst." in resolved.system_prompt_extra
    assert "Security-focused." in resolved.system_prompt_extra


@pytest.mark.skip(reason="Requires .bouzecode/profiles/ directory (not in OSS worktree)")
def test_default_profile_loads():
    """The shipped default.yaml profile loads and has expected structure."""
    profiles_dir = Path(__file__).resolve().parents[3] / ".bouzecode" / "profiles"
    profiles = load_profiles_from_dir(profiles_dir)
    assert "default" in profiles
    default = profiles["default"]
    assert default.tools == []
    assert default.hooks == []
    assert default.skills == []
