# [desc] Skills declared by an installed plugin are offered by load_skills, even when plugins.json carries another workstation's import_root. [/desc]
"""Plugin skills, end to end: plugins.json in a fake HOME → load_skills() lists them.

Real files only: a fake plugin package is written under tmp_path and put on sys.path,
plugins.json is written in a tmp CONFIG_DIR. No function of bouzecode is replaced.
"""
import json

import pytest

from bouzecode.backend.plugin import list_plugins
from bouzecode.backend.tools.skill import load_skills


def _write_skill_plugin(site, pkg, skill_name):
    """An importable package shipping plugin.json + one declared skill."""
    root = site / pkg
    (root / "skills" / skill_name).mkdir(parents=True)
    (root / "__init__.py").write_text("", encoding="utf-8")
    (root / "plugin.json").write_text(json.dumps({
        "name": pkg, "package": pkg.replace("_", "-"),
        "skills": [f"skills/{skill_name}/skill.md"],
    }), encoding="utf-8")
    (root / "skills" / skill_name / "skill.md").write_text(
        f"---\nname: {skill_name}\ndescription: from the plugin\n---\n\nplugin body\n",
        encoding="utf-8")
    return root


def _register(cfg_dir, pkg, import_root):
    (cfg_dir / "plugins.json").write_text(json.dumps({"plugins": {pkg: {
        "name": pkg, "scope": "user", "package": pkg.replace("_", "-"),
        "import_root": str(import_root), "enabled": True,
    }}}), encoding="utf-8")


@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    cfg_dir = tmp_path / "home" / ".bouzecode"
    cfg_dir.mkdir(parents=True)
    monkeypatch.setattr("bouzecode.backend.core.config.CONFIG_DIR", cfg_dir)
    monkeypatch.delenv("BOUZECODE_NO_PLUGINS", raising=False)
    workdir = tmp_path / "work"
    workdir.mkdir()
    monkeypatch.chdir(workdir)
    site = tmp_path / "site"
    site.mkdir()
    monkeypatch.syspath_prepend(str(site))
    return cfg_dir, site


def test_an_installed_plugin_skill_is_listed(fake_home):
    cfg_dir, site = fake_home
    _register(cfg_dir, "skillplug_listed", _write_skill_plugin(site, "skillplug_listed", "plug-listed"))

    skill = {s.name: s for s in load_skills()}["plug-listed"]

    assert skill.source == "plugin"
    assert "plugin body" in skill.prompt


def test_a_user_skill_of_the_same_name_beats_the_plugin(fake_home):
    cfg_dir, site = fake_home
    _register(cfg_dir, "skillplug_shadow", _write_skill_plugin(site, "skillplug_shadow", "plug-shadow"))
    user_skill = cfg_dir / "skills" / "plug-shadow"
    user_skill.mkdir(parents=True)
    (user_skill / "skill.md").write_text(
        "---\nname: plug-shadow\ndescription: mine\n---\n\nuser body\n", encoding="utf-8")

    skill = {s.name: s for s in load_skills()}["plug-shadow"]

    assert skill.source == "user"


def test_a_stale_import_root_is_resolved_again_from_the_environment(fake_home):
    """plugins.json copied from another workstation: its .venv path does not exist here."""
    cfg_dir, site = fake_home
    real_root = _write_skill_plugin(site, "skillplug_moved", "plug-moved")
    _register(cfg_dir, "skillplug_moved", site.parent / "other_pc" / ".venv" / "skillplug_moved")

    entry = next(e for e in list_plugins() if e.name == "skillplug_moved")

    assert entry.import_root == real_root
    assert "plug-moved" in {s.name for s in load_skills()}


def test_an_unresolvable_plugin_is_reported_not_silent(fake_home, capsys):
    cfg_dir, _ = fake_home
    _register(cfg_dir, "skillplug_gone", cfg_dir / "nowhere" / "skillplug_gone")

    entry = next(e for e in list_plugins() if e.name == "skillplug_gone")

    assert entry.manifest is None
    reported = capsys.readouterr().err
    assert "skillplug_gone" in reported
    assert "introuvable" in reported
