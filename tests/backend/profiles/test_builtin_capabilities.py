# [desc] Built-in capability fragments (deferred) are composed into every depth-0
# agent prompt by typology, without the cwd project declaring them. [/desc]
"""Composition (pas heritage) des capabilities packagees.

La regle 'Bash long -> deferred=True' vit dans un fragment package
(profiles/builtin/deferred.yaml), PAS dans les profils des projets cibles.
get_agent_profile_extra doit la composer avec le profil typologie quel qu'il
soit — y compris une typologie qui ne mentionne nulle part le deferred.
"""
import pytest

from bouzecode.backend.core import context, profile_extra


@pytest.fixture
def project(tmp_path):
    """Projet temp avec un profil typologie 'feature' SANS regle deferred."""
    pdir = tmp_path / ".bouzecode" / "profiles"
    pdir.mkdir(parents=True)
    (pdir / "feature.yaml").write_text(
        "name: feature\nsystem_prompt_extra: |\n  REGLE_FEATURE_SPECIFIQUE\n",
        encoding="utf-8",
    )
    return tmp_path


def _extra(monkeypatch, project, classification):
    monkeypatch.chdir(project)
    profile_extra._DEFAULT_PROFILE_EXTRA_CACHE.clear()
    return context.get_agent_profile_extra(classification)


def test_capability_composed_with_typology_profile(monkeypatch, project):
    """La typologie 'feature' garde sa regle ET recoit la capability deferred."""
    extra = _extra(monkeypatch, project, "feature")
    assert "REGLE_FEATURE_SPECIFIQUE" in extra  # profil typologie preserve
    assert "deferred=True" in extra              # capability composee par-dessus


def test_capability_composed_even_when_profile_absent(monkeypatch, project):
    """Typologie inconnue du projet -> profil None, mais la capability reste."""
    extra = _extra(monkeypatch, project, "typologie-inexistante")
    assert "deferred=True" in extra


def test_no_double_injection_when_default_resolved(monkeypatch, project):
    """default.yaml ne porte plus la regle : default resolu + fragment compose
    => la consigne deferred apparait UNE seule fois (pas de double injection)."""
    pdir = project / ".bouzecode" / "profiles"
    (pdir / "default.yaml").write_text(
        "name: default\nsystem_prompt_extra: |\n  REGLE_DEFAULT\n", encoding="utf-8",
    )
    extra = _extra(monkeypatch, project, "default")
    assert "REGLE_DEFAULT" in extra
    assert extra.count("deferred=True") == 1
