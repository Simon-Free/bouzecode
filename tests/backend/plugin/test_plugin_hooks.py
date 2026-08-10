# [desc] Test: a plugin's HOOK_DEFS are registered into the named-hook catalog and referencable by a profile. [/desc]
"""Plugin-contributed hooks, mirror of plugin tools (TOOL_DEFS → HOOK_DEFS).

A fake plugin package on disk (manifest with `hooks`) → register_plugin_hooks imports
its module and registers HOOK_DEFS into the pipeline catalog → a profile can wire it
by name. No unittest.mock — real on-disk package + pytest.monkeypatch."""
from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

from bouzecode.backend.agent.hooks import pipeline
from bouzecode.backend.plugin import loader
from bouzecode.backend.plugin.types import PluginEntry, PluginManifest, PluginScope


@pytest.fixture()
def fake_plugin(tmp_path: Path):
    pkg = tmp_path / "fakeplughook_pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "plugin.json").write_text(
        '{"name": "fakeplughook", "hooks": ["hooks"]}', encoding="utf-8")
    (pkg / "hooks.py").write_text(textwrap.dedent("""
        from bouzecode.backend.agent.hooks.pipeline import HookDef

        def on_done(ctx):
            return None

        HOOK_DEFS = [HookDef(name="fakeplug_hook", event="on_completion", func=on_done)]
    """), encoding="utf-8")
    entry = PluginEntry(
        name="fakeplughook", scope=PluginScope.USER, package="fakeplughook",
        import_root=pkg, enabled=True,
        manifest=PluginManifest(name="fakeplughook", hooks=["hooks"]),
    )
    yield entry
    pipeline.reset_named()
    pipeline.reset()
    sys.modules.pop("fakeplughook_pkg", None)
    sys.modules.pop("fakeplughook_pkg.hooks", None)


def test_plugin_hook_registered_and_referencable(fake_plugin, monkeypatch):
    monkeypatch.setattr(loader, "_enabled", lambda scope=None: [fake_plugin])

    count = loader.register_plugin_hooks()
    assert count == 1

    hook = pipeline.get_named_hook("fakeplug_hook")
    assert hook is not None
    assert hook.event == "on_completion"

    # a profile referencing the plugin hook by name wires it like a builtin.
    assert pipeline.register_named("fakeplug_hook") is True
    assert hook.func in pipeline.registered_events()["on_completion"]
