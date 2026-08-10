# [desc] Plugin store + manifest tests: register a fake pip-installed plugin and assert discovery/enable. [/desc]
"""Plugin system: manifest parsing, registry round-trip, tool discovery.

No real pip / no network: a fake plugin package is written to a tmp import root
and the install step is redirected there via monkeypatch.
"""
import json
import sys

import pytest

from bouzecode.backend.plugin import (
    install_plugin, list_plugins, get_plugin, enable_plugin, disable_plugin,
    register_plugin_tools,
)
from bouzecode.backend.plugin.types import PluginManifest, PluginScope


def _write_fake_plugin(root, pkg="fake_plugin", tool_name="FakePluginTool"):
    """Create an importable package shipping plugin.json + a TOOL_DEFS module."""
    pkg_dir = root / pkg
    pkg_dir.mkdir(parents=True)
    (pkg_dir / "__init__.py").write_text("", encoding="utf-8")
    (pkg_dir / "plugin.json").write_text(json.dumps({
        "name": pkg, "package": pkg.replace("_", "-"),
        "tools": ["mytool"], "dependencies": ["some-dep"],
    }), encoding="utf-8")
    # Pure-dict TOOLS contract: NO bouzecode import — bouzecode builds the ToolDef.
    (pkg_dir / "mytool.py").write_text(
        "def _run(params, config):\n    return 'ran'\n"
        f"_NAME = {tool_name!r}\n"
        "TOOLS = [{'name': _NAME, 'description': 'x', "
        "'input_schema': {'type': 'object', 'properties': {}}, "
        "'func': _run, 'read_only': True}]\n",
        encoding="utf-8",
    )
    return pkg_dir


@pytest.fixture
def fake_install(tmp_path, monkeypatch):
    """Point CONFIG_DIR + the pip-install boundary at tmp; return install helper."""
    cfg_dir = tmp_path / "cfg"
    cfg_dir.mkdir()
    monkeypatch.setattr("bouzecode.backend.core.config.CONFIG_DIR", cfg_dir)

    site = tmp_path / "site"
    site.mkdir()
    sys.path.insert(0, str(site))

    def _fake_pip(package, index_url):
        _write_fake_plugin(site, pkg=package.replace("-", "_"))
        return True, "installed"

    monkeypatch.setattr("bouzecode.backend.plugin.store._pip_install", _fake_pip)
    yield site
    sys.path.remove(str(site))


def test_manifest_from_import_root(tmp_path):
    root = _write_fake_plugin(tmp_path)
    manifest = PluginManifest.from_import_root(root)
    assert manifest.name == "fake_plugin"
    assert manifest.tools == ["mytool"]
    assert manifest.dependencies == ["some-dep"]


def test_plugin_tool_module_has_no_bouzecode_import(tmp_path):
    """The TOOLS contract is pure dicts: a plugin module must not import bouzecode."""
    root = _write_fake_plugin(tmp_path)
    source = (root / "mytool.py").read_text(encoding="utf-8")
    assert "bouzecode" not in source
    assert "import tool_registry" not in source


def test_install_registers_and_discovers_tool(fake_install):
    ok, msg = install_plugin("fake-plugin", scope=PluginScope.USER)
    assert ok, msg

    entry = get_plugin("fake_plugin")
    assert entry is not None
    assert entry.package == "fake-plugin"
    assert entry.enabled

    count = register_plugin_tools()
    assert count >= 1
    from bouzecode.backend.core.tool_registry import get_tool
    assert get_tool("FakePluginTool") is not None


def test_disable_excludes_from_registration(fake_install):
    install_plugin("fake-plugin", scope=PluginScope.USER)
    disable_plugin("fake_plugin")
    assert get_plugin("fake_plugin").enabled is False
    enable_plugin("fake_plugin")
    assert get_plugin("fake_plugin").enabled is True
