# [desc] Tests for the typologies service: built from real profile YAMLs + builtin agent defs, default always first. [/desc]
"""Tests for bouzecode.web_v2.services.typologies.

list_typologies() is now derived from real profile YAMLs (project/global/extra
dirs) plus builtin agent definitions — there is no standalone web_typologies.yaml
anymore. We isolate the global profiles dir (config.CONFIG_DIR), the extra-dir
registry and the builtin agent definitions so counts are machine-independent.
"""
from __future__ import annotations

import pytest
import yaml

from bouzecode.web_v2.services.typologies import get_typology, list_typologies

_PROFILE = {"skills": [], "tools": [], "hooks": [], "model": ""}


_SYSTEM = {"general-purpose", "meta-agent", "manager"}


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    """No real ~/.bouzecode profiles and no extra dirs — so a test sees only 'default',
    the always-present system agents, plus the project profiles it creates itself."""
    from bouzecode.backend.core import config, paths
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path / "global")  # user_global_dir() -> empty
    paths.register_extra_dirs([])
    yield
    paths.register_extra_dirs([])


@pytest.fixture
def typology_project(tmp_path):
    """A project dir holding .bouzecode/profiles/{analyst,refacto}.yaml."""
    profiles_dir = tmp_path / "proj" / ".bouzecode" / "profiles"
    profiles_dir.mkdir(parents=True)
    for name, desc in [("analyst", "Analyst agent"), ("refacto", "Refacto agent")]:
        data = {"name": name, "system_prompt_extra": desc, **_PROFILE}
        (profiles_dir / f"{name}.yaml").write_text(
            yaml.dump(data, allow_unicode=True), encoding="utf-8")
    return str(tmp_path / "proj")


def test_list_typologies_includes_default_first(typology_project):
    result = list_typologies(typology_project)
    assert result[0]["name"] == "default"
    assert result[0]["profile"] == ""


def test_list_typologies_names(typology_project):
    names = [t["name"] for t in list_typologies(typology_project)]
    assert names[0] == "default"
    assert {"analyst", "refacto"} <= set(names)   # project profiles
    assert _SYSTEM <= set(names)                # always-present system agents


def test_list_typologies_count(typology_project):
    # default + 2 project profiles + the builtin system agents (derived, not hardcoded,
    # so adding a new system profile does not break this test).
    from bouzecode.backend.profiles.discovery import load_system_profiles

    names = [t["name"] for t in list_typologies(typology_project)]
    expected = {"default", "analyst", "refacto"} | set(load_system_profiles())
    assert set(names) == expected
    assert len(names) == len(set(names))  # no duplicate typologies


def test_get_typology_found(typology_project):
    t = get_typology("analyst", typology_project)
    assert t is not None
    assert t["profile"] == "analyst"
    assert t["description"] == "Analyst agent"


def test_get_typology_not_found(typology_project):
    assert get_typology("nonexistent", typology_project) is None


def test_get_typology_default_always_exists(typology_project):
    t = get_typology("default", typology_project)
    assert t is not None
    assert t["profile"] == ""


def test_list_typologies_no_profiles(tmp_path):
    """A project with no profiles dir yields 'default' + the builtin system agents,
    and nothing else (no stray project profiles leak in)."""
    from bouzecode.backend.profiles.discovery import load_system_profiles

    result = list_typologies(str(tmp_path / "empty"))
    names = [t["name"] for t in result]
    assert names[0] == "default"
    assert _SYSTEM <= set(names)  # core system agents always present
    # With no project/global/extra profiles, the set is exactly default + system agents.
    assert set(names) == {"default"} | set(load_system_profiles())


def test_list_typologies_none_path():
    """With None project_path, still returns at least 'default' first."""
    result = list_typologies(None)
    assert result[0]["name"] == "default"
    assert len(result) >= 1


def test_system_agents_are_included():
    """The 3 builtin system agents appear as typologies, with descriptions."""
    typ = list_typologies(None)
    names = [t["name"] for t in typ]
    assert names[0] == "default"
    assert _SYSTEM <= set(names)
    meta = next(t for t in typ if t["name"] == "meta-agent")
    assert meta["profile"] == "meta-agent"
    assert meta["description"]
