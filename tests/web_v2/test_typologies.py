# [desc] Tests for the typologies service: listing, lookup, defaults, missing files, and invalid YAML. [/desc]
"""Tests for bouzecode.web_v2.services.typologies."""
from __future__ import annotations

import pytest
import yaml

from bouzecode.web_v2.services.typologies import get_typology, list_typologies


@pytest.fixture(autouse=True)
def _isolate_global_typologies(tmp_path, monkeypatch):
    """Prevent the real ~/.bouzecode/web_typologies.yaml from leaking into tests."""
    fake_global = tmp_path / "_no_global" / "web_typologies.yaml"
    monkeypatch.setattr(
        "bouzecode.web_v2.services.typologies._GLOBAL_FILE", fake_global
    )


@pytest.fixture
def typology_project(tmp_path):
    """Create a project dir with .bouzecode/web_typologies.yaml."""
    data = {
        "typologies": [
            {"name": "focus", "description": "Focus agent", "profile": "focus"},
            {"name": "refacto", "description": "Refacto agent", "profile": "refacto"},
        ]
    }
    cfg_dir = tmp_path / ".bouzecode"
    cfg_dir.mkdir()
    (cfg_dir / "web_typologies.yaml").write_text(
        yaml.dump(data, allow_unicode=True), encoding="utf-8"
    )
    return str(tmp_path)


def test_list_typologies_includes_default_first(typology_project):
    result = list_typologies(typology_project)
    assert result[0]["name"] == "default"
    assert result[0]["profile"] == ""


def test_list_typologies_names(typology_project):
    names = [t["name"] for t in list_typologies(typology_project)]
    assert names == ["default", "focus", "refacto"]


def test_list_typologies_count(typology_project):
    assert len(list_typologies(typology_project)) == 3


def test_get_typology_found(typology_project):
    t = get_typology("focus", typology_project)
    assert t is not None
    assert t["profile"] == "focus"
    assert t["description"] == "Focus agent"


def test_get_typology_not_found(typology_project):
    assert get_typology("nonexistent", typology_project) is None


def test_get_typology_default_always_exists(typology_project):
    t = get_typology("default", typology_project)
    assert t is not None
    assert t["profile"] == ""


def test_list_typologies_no_file(tmp_path):
    """Without a config file, only 'default' is returned."""
    result = list_typologies(str(tmp_path))
    assert len(result) == 1
    assert result[0]["name"] == "default"


def test_list_typologies_none_path():
    """With None project_path, returns at least 'default'."""
    result = list_typologies(None)
    assert result[0]["name"] == "default"
    assert len(result) >= 1


def test_list_typologies_invalid_yaml(tmp_path):
    """Invalid YAML should not crash, just return default."""
    cfg_dir = tmp_path / ".bouzecode"
    cfg_dir.mkdir()
    (cfg_dir / "web_typologies.yaml").write_text("{{{{invalid", encoding="utf-8")
    result = list_typologies(str(tmp_path))
    assert len(result) == 1
    assert result[0]["name"] == "default"
