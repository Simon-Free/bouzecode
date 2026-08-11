# [desc] /agent command: lists agents/profiles and switches the session typology (system prompt + tools + model) while preserving context_state.notes; meta-agent built-in exists. [/desc]
"""tmp project dir (chdir) + a written profile yaml — no mocking lib needed."""
import types

import pytest

import bouzecode.backend.tools.registration  # noqa: F401  (registers builtin tools)
from bouzecode.backend.commands.extensions.agent_switch import cmd_agent
from bouzecode.backend.core.tool_registry import is_enabled, reset_disabled


@pytest.fixture(autouse=True)
def _clean_tools():
    reset_disabled()
    yield
    reset_disabled()


@pytest.fixture(autouse=True)
def _isolate_global(tmp_path, monkeypatch):
    """Point the global profile dir + extra-dir registry at empty tmp so tests don't read real ~/.bouzecode."""
    from bouzecode.backend.core import config, paths
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path / "home")
    paths.register_extra_dirs([])
    yield
    paths.register_extra_dirs([])


def _state():
    return types.SimpleNamespace(
        context_state=types.SimpleNamespace(notes={"methodology": "garder ce contexte"}))


def _write_profile(tmp_path, name, body):
    d = tmp_path / ".bouzecode" / "profiles"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.yaml").write_text(body, encoding="utf-8")


def test_meta_agent_is_a_builtin():
    from bouzecode.backend.profiles import load_system_profiles
    system = load_system_profiles()
    assert "meta-agent" in system
    meta = system["meta-agent"]
    assert meta.kind == "system"
    assert "creating-agents" in meta.system_prompt_extra
    assert "adding-tools" in meta.system_prompt_extra
    # The 3 system agents are always present, never the composable fragment.
    assert {"general-purpose", "meta-agent", "manager"} <= set(system)
    assert "deferred" not in system


def test_switch_to_profile_applies_tools_model_and_prompt(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_profile(tmp_path, "reviewer-x", (
        "name: reviewer-x\n"
        "tools: [Read, Grep]\n"
        "model: claude-opus-4-8\n"
        "system_prompt_extra: Tu es un relecteur adverse.\n"
    ))
    config, state = {"model": "claude-sonnet-4-6"}, _state()

    cmd_agent("reviewer-x", state, config)

    assert config["_active_agent"] == "reviewer-x"
    assert config["model"] == "claude-opus-4-8"
    assert config["_agent_system_prompt_extra"] == "Tu es un relecteur adverse."
    # allowlist applied: kept tools + essentials enabled, the rest disabled
    assert is_enabled("Read") and is_enabled("Grep")
    assert is_enabled("FinalAnswer")  # essential, kept even though not listed
    assert not is_enabled("Write") and not is_enabled("Bash")
    # variable context preserved
    assert state.context_state.notes == {"methodology": "garder ce contexte"}


def test_system_prompt_includes_active_agent_extra(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_profile(tmp_path, "p1", "name: p1\nsystem_prompt_extra: PERSONA-MARKER-42\n")
    config = {}
    cmd_agent("p1", _state(), config)
    from bouzecode.backend.core.context import build_system_prompt
    assert "PERSONA-MARKER-42" in build_system_prompt(config)
    assert "# Active agent profile" in build_system_prompt(config)


def test_revert_restores_defaults(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_profile(tmp_path, "p2", "name: p2\ntools: [Read]\nsystem_prompt_extra: x\n")
    config = {}
    cmd_agent("p2", _state(), config)
    assert not is_enabled("Bash")

    cmd_agent("default", _state(), config)
    assert "_agent_system_prompt_extra" not in config
    assert "_active_agent" not in config
    assert is_enabled("Bash") and is_enabled("Write")  # all re-enabled


def test_switch_to_builtin_meta_agent(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config = {}
    cmd_agent("meta-agent", _state(), config)
    assert config["_active_agent"] == "meta-agent"
    assert "creating-agents" in config["_agent_system_prompt_extra"]


def test_unknown_agent_is_noop(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config = {"model": "m0"}
    cmd_agent("does-not-exist", _state(), config)
    assert "_active_agent" not in config
    assert config["model"] == "m0"


def test_list_mode_runs(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    _write_profile(tmp_path, "p3", "name: p3\ntools: [Read]\nsystem_prompt_extra: hello\n")
    assert cmd_agent("", _state(), {}) is True
    out = capsys.readouterr().out
    assert "p3" in out and "meta-agent" in out
    # The 3 system agents are listed; the composable fragment never is.
    assert "System agents" in out
    assert "general-purpose" in out and "manager" in out
    assert "deferred" not in out


def test_general_purpose_is_a_system_agent(tmp_path, monkeypatch):
    """general-purpose is now a real (minimal) system agent: switching to it sets the
    active agent and, having no tools allowlist, restricts nothing."""
    monkeypatch.chdir(tmp_path)
    _write_profile(tmp_path, "p4", "name: p4\ntools: [Read]\nsystem_prompt_extra: x\n")
    config = {}
    cmd_agent("p4", _state(), config)          # specialize first
    assert config["_active_agent"] == "p4"
    cmd_agent("general-purpose", _state(), config)
    assert config["_active_agent"] == "general-purpose"
    assert is_enabled("Bash") and is_enabled("Write")  # empty tools => no restriction


def test_profile_skills_are_preloaded_into_the_prompt(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    skills_dir = tmp_path / "home" / "skills"   # CONFIG_DIR is tmp_path/home (see _isolate_global)
    skills_dir.mkdir(parents=True)
    (skills_dir / "myskill.md").write_text(
        "---\nname: myskill\ndescription: d\n---\nSKILL-BODY-MARKER-7", encoding="utf-8")
    _write_profile(tmp_path, "specialist", "name: specialist\nskills: [myskill]\n")

    config = {}
    cmd_agent("specialist", _state(), config)
    assert config["_profile_skills"] == ["myskill"]

    from bouzecode.backend.core.context import build_system_prompt
    assert "SKILL-BODY-MARKER-7" in build_system_prompt(config)

    cmd_agent("default", _state(), config)
    assert "_profile_skills" not in config


def test_deferred_builtin_is_not_switchable(tmp_path, monkeypatch):
    """The composable builtin profile must only resolve internally, never via /agent."""
    monkeypatch.chdir(tmp_path)
    config = {"model": "m0"}
    cmd_agent("deferred", _state(), config)
    assert "_active_agent" not in config       # unknown -> no-op
    assert config["model"] == "m0"


def _prof(name, **kw):
    from bouzecode.backend.profiles.models import AgentProfile
    return AgentProfile(name=name, **kw)


def test_agent_list_shows_two_sections(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    from bouzecode.backend.profiles import catalog
    monkeypatch.setattr(
        catalog, "installed_and_available",
        lambda: ({"inst-a": _prof("inst-a", tools=["Read"])},
                 {"avail-b": _prof("avail-b", tools=["Bash"])}))
    assert cmd_agent("", _state(), {}) is True
    out = capsys.readouterr().out
    assert "Installed agents" in out and "inst-a" in out
    assert "Available agents" in out and "avail-b" in out
    assert "/agent install" in out


def test_agent_install_writes_local_yaml(tmp_path, monkeypatch, capsys):
    import yaml
    from bouzecode.backend.core import config
    from bouzecode.backend.multi_agent import plugin_resolver
    from bouzecode.backend.profiles import catalog
    monkeypatch.setattr(
        catalog, "list_catalog_profiles",
        lambda: {"foo": _prof("foo", tools=["Read"], requires_plugins=["p1"])})
    monkeypatch.setattr(plugin_resolver, "ensure_plugins", lambda reqs: ([], []))
    assert cmd_agent("install foo", _state(), {}) is True
    dest = config.CONFIG_DIR / "profiles" / "foo.yaml"
    assert dest.exists()
    data = yaml.safe_load(dest.read_text(encoding="utf-8"))
    assert data["name"] == "foo"
    assert data["tools"] == ["Read"]
    assert data["requires_plugins"] == ["p1"]


def test_agent_install_surfaces_plugin_errors(tmp_path, monkeypatch, capsys):
    from bouzecode.backend.multi_agent import plugin_resolver
    from bouzecode.backend.profiles import catalog
    monkeypatch.setattr(
        catalog, "list_catalog_profiles",
        lambda: {"foo": _prof("foo", tools=["Read"], requires_plugins=["p1"])})
    monkeypatch.setattr(
        plugin_resolver, "ensure_plugins", lambda reqs: ([], ["BOOM index"]))
    assert cmd_agent("install foo", _state(), {}) is True
    out = capsys.readouterr().out
    assert "BOOM index" in out


def test_agent_install_unknown_warns(tmp_path, monkeypatch, capsys):
    from bouzecode.backend.core import config
    from bouzecode.backend.profiles import catalog
    monkeypatch.setattr(catalog, "list_catalog_profiles", lambda: {})
    assert cmd_agent("install nope", _state(), {}) is True
    out = capsys.readouterr().out
    assert "unknown agent" in out.lower()
    assert not (config.CONFIG_DIR / "profiles" / "nope.yaml").exists()
