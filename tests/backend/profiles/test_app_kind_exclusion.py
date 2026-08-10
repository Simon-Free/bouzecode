"""`kind: app` = agent standalone d'une app hôte. Il partage le FORMAT de
profil mais n'est PAS un agent dev bouzecode : exclu du set switchable/spawnable (/agent,
Agent()) ET des typologies dispatchables (manager). Son app le charge DIRECTEMENT par path."""
from bouzecode.backend.profiles import discovery, loader


def _write(path, name, kind=None):
    body = f"name: {name}\nsystem_prompt_extra: hi\n"
    if kind:
        body += f"kind: {kind}\n"
    path.write_text(body, encoding="utf-8")


def test_app_profile_excluded_from_switchable_set(monkeypatch, tmp_path):
    _write(tmp_path / "app_agent.yaml", "app_agent", kind="app")
    _write(tmp_path / "dev_agent.yaml", "dev_agent")
    monkeypatch.setattr(discovery, "profile_search_dirs", lambda include_builtin=False: [tmp_path])
    profs = discovery.load_user_profiles()
    assert "dev_agent" in profs          # normal dev profile stays switchable
    assert "app_agent" not in profs      # app agent excluded
    assert discovery.resolve_agent_profile("app_agent") is None


def test_app_profile_still_loads_directly_by_path(tmp_path):
    _write(tmp_path / "focusish.yaml", "focusish", kind="app")
    prof = loader.load_profile_from_path(tmp_path / "focusish.yaml")
    assert prof.name == "focusish" and prof.kind == "app"
    assert prof.system_prompt_extra == "hi"   # host app path unaffected


def test_app_profile_not_a_dispatchable_typology(monkeypatch, tmp_path):
    pdir = tmp_path / "profiles"
    pdir.mkdir()
    _write(pdir / "focusish.yaml", "focusish", kind="app")
    _write(pdir / "revu.yaml", "revu")
    from bouzecode.backend.core import paths
    monkeypatch.setattr(paths, "get_extra_dirs", lambda: [tmp_path])
    from bouzecode.web_v2.services.typologies import list_typologies
    names = [t["name"] for t in list_typologies(None)]
    assert "revu" in names
    assert "focusish" not in names
