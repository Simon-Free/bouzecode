"""`--profile <name>` doit précharger les skills DÉCLARÉES du profil (chemin sanctionné
render_profile_skills), comme /agent et le manager. Régression : le chemin --profile ne
posait que la persona, jamais `_profile_skills` → un agent dispatché ne voyait aucune de
ses skills (ex. conversation-download raté au tour 1)."""
from bouzecode.backend.profiles import models
from bouzecode.ui import cli


def _stub_resolver(monkeypatch, profile):
    # apply_profile_skills imports resolve_agent_profile from the package at call time.
    from bouzecode.backend import profiles
    monkeypatch.setattr(profiles, "resolve_agent_profile", lambda name: profile)


def test_declared_skills_are_preloaded(monkeypatch):
    prof = models.AgentProfile(name="dbg", skills=["conversation-download", "troubleshooting"])
    _stub_resolver(monkeypatch, prof)
    config = {}
    cli.apply_profile_skills(config, "dbg")
    assert config["_profile_skills"] == ["conversation-download", "troubleshooting"]


def test_profile_without_skills_sets_nothing(monkeypatch):
    _stub_resolver(monkeypatch, models.AgentProfile(name="analyst", skills=[]))
    config = {}
    cli.apply_profile_skills(config, "analyst")
    assert "_profile_skills" not in config


def test_unknown_profile_sets_nothing(monkeypatch):
    _stub_resolver(monkeypatch, None)
    config = {}
    cli.apply_profile_skills(config, "nope")
    assert "_profile_skills" not in config
