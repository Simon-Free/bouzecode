# [desc] ensure_plugins resolver: installs required plugins, returns their tool names, surfaces install errors. [/desc]
"""Profile `requires_plugins` resolution at launch.

ensure_plugins must install missing plugins (scope user), return the tool names
they contribute, and surface install failures instead of swallowing them.
"""
import json
import sys

import pytest

from bouzecode.backend.multi_agent.plugin_resolver import ensure_plugins


def _write_fake_plugin(site, pkg, tool_name):
    pkg_dir = site / pkg
    pkg_dir.mkdir(parents=True)
    (pkg_dir / "__init__.py").write_text("", encoding="utf-8")
    (pkg_dir / "plugin.json").write_text(json.dumps({
        "name": pkg, "package": pkg.replace("_", "-"), "tools": ["mytool"],
    }), encoding="utf-8")
    (pkg_dir / "mytool.py").write_text(
        "def _run(params, config):\n    return 'ran'\n"
        f"_NAME = {tool_name!r}\n"
        "TOOLS = [{'name': _NAME, 'description': 'x', "
        "'input_schema': {'type': 'object', 'properties': {}}, "
        "'func': _run, 'read_only': True}]\n",
        encoding="utf-8",
    )


@pytest.fixture
def site(tmp_path, monkeypatch):
    cfg_dir = tmp_path / "cfg"; cfg_dir.mkdir()
    monkeypatch.setattr("bouzecode.backend.core.config.CONFIG_DIR", cfg_dir)
    site_dir = tmp_path / "site"; site_dir.mkdir()
    sys.path.insert(0, str(site_dir))
    yield site_dir
    sys.path.remove(str(site_dir))


def test_ensure_plugins_installs_and_returns_tool_names(site, monkeypatch):
    def _fake_pip(package, index_url):
        _write_fake_plugin(site, package.replace("-", "_"), "GitlabTool")
        return True, "installed"
    monkeypatch.setattr("bouzecode.backend.plugin.store._pip_install", _fake_pip)

    tools, errors = ensure_plugins(["demo-gitlab-plugin"])
    assert errors == []
    assert "GitlabTool" in tools


def test_ensure_plugins_surfaces_install_error(site, monkeypatch):
    def _fail_pip(package, index_url):
        return False, "pip install failed: package index unreachable"
    monkeypatch.setattr("bouzecode.backend.plugin.store._pip_install", _fail_pip)

    tools, errors = ensure_plugins(["demo-missing-plugin"])
    assert tools == []
    assert any("package index unreachable" in e for e in errors)


def test_ensure_plugins_installs_from_git_source(site, monkeypatch):
    """A {name, source: git+...} requirement clones+installs via the git path."""
    seen = {}

    def _fake_clone(source):
        seen["source"] = source
        _write_fake_plugin(site, "demo_gitplugin", "GitTool")
        return True, "installed"
    monkeypatch.setattr("bouzecode.backend.plugin.store._clone_and_install", _fake_clone)

    tools, errors = ensure_plugins([
        {"name": "demo-gitplugin", "source": "git+https://gitlab.example.com/x/demo-gitplugin.git"},
    ])
    assert errors == []
    assert "GitTool" in tools
    assert seen["source"].startswith("git+https://")

