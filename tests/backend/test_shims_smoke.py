# [desc] Non-regression : les six commandes de la couche oss_shims sont réellement dispatchables. [/desc]
"""Les six commandes OSS passent par `handle_slash`, pour de vrai.

Le défaut que ces tests verrouillent : `dispatcher.handle_slash` appelle
`handler(args, state, config)`, alors que `cmd_memory`, `cmd_mcp` et `cmd_plugin`
étaient déclarés `(args, config)`. `/memory`, `/mcp` et `/plugin` levaient donc un
`TypeError` au premier usage. Le bug a survécu parce que l'ancienne version de ce
fichier n'appelait rien : elle vérifiait la présence de la clé dans `COMMANDS`, et
les deux appels qu'elle tentait étaient enveloppés dans `except Exception: pass` —
qui avalait précisément le `TypeError` recherché.

Second défaut couvert ici : le dispatcher JETTE la valeur de retour du handler.
Les shims qui rendaient leur sortie sous forme de chaîne (`/mcp list`,
`/memory list`, `/plugin list`) n'affichaient donc rien.

Aucun `unittest.mock` : les magasins (mémoire, plugins, MCP) sont repointés sur
`tmp_path`, si bien que la commande s'exécute pour de bon sans lire l'état réel de
la machine ni ouvrir une connexion.
"""
from __future__ import annotations

import pytest

from bouzecode.backend.commands import handle_slash
from bouzecode.backend.commands.dispatcher import COMMANDS, _CMD_META

OSS_COMMAND_NAMES = ("voice", "mcp", "plugin", "memory", "video", "video-wizard")


class _State:
    """The shims only ever store the state on config; nothing reads it back."""

    messages: list = []


@pytest.fixture
def config():
    return {"permission_mode": "accept-all"}


@pytest.fixture(autouse=True)
def _empty_stores(tmp_path, monkeypatch):
    """Point every user-scoped store the shims read at an empty tmp dir."""
    import memory.store as memory_store
    import plugin.store as plugin_store
    import mcp.config as mcp_config

    monkeypatch.chdir(tmp_path)  # project scope of all three stores
    monkeypatch.setattr(memory_store, "USER_MEMORY_DIR", tmp_path / "memory")
    monkeypatch.setattr(plugin_store, "USER_PLUGIN_DIR", tmp_path / "plugins")
    monkeypatch.setattr(plugin_store, "USER_PLUGIN_CFG", tmp_path / "plugins.json")
    monkeypatch.delenv(plugin_store.PLUGIN_PATH_ENV, raising=False)
    # No server config → initialize_mcp() returns immediately, no subprocess.
    monkeypatch.setattr(mcp_config, "USER_MCP_CONFIG", tmp_path / "mcp.json")


@pytest.fixture(autouse=True)
def _wizard_quits_immediately(monkeypatch):
    """`/video-wizard` is interactive by nature. Its first prompt is replaced by a
    'user quit' so the DISPATCH path is exercised without reading stdin."""
    import commands.video_wizard as video_wizard
    monkeypatch.setattr(video_wizard, "run_video_wizard",
                        lambda state, config, is_tg: None)


@pytest.mark.parametrize("name", OSS_COMMAND_NAMES)
def test_every_oss_command_is_registered_and_documented(name):
    assert name in COMMANDS, f"/{name} is not dispatchable"
    assert name in _CMD_META, f"/{name} is dispatchable but absent from /help"
    description, _subcommands = _CMD_META[name]
    assert description.strip(), f"/{name} has an empty help line"


@pytest.mark.parametrize("line", [
    "/voice status",
    "/mcp list",
    "/plugin list",
    "/memory list",
    "/video status",
    "/video-wizard",
])
def test_oss_command_runs_through_the_dispatcher(line, config):
    """THE regression: each command really runs when typed, no TypeError."""
    assert handle_slash(line, _State(), config) is True


def test_mcp_list_prints_its_result(config, capsys):
    handle_slash("/mcp list", _State(), config)
    assert "No MCP servers configured" in capsys.readouterr().out


def test_plugin_list_prints_its_result(config, capsys):
    handle_slash("/plugin list", _State(), config)
    assert "No plugins installed" in capsys.readouterr().out


def test_memory_list_prints_its_result(config, capsys):
    handle_slash("/memory list", _State(), config)
    assert "No memories stored" in capsys.readouterr().out


def test_memory_list_shows_a_stored_entry(config, capsys, tmp_path):
    """Not just the empty case: a real memory file comes back on the terminal."""
    import memory.store as memory_store
    memory_store.USER_MEMORY_DIR.mkdir(parents=True)
    (memory_store.USER_MEMORY_DIR / "deploy-notes.md").write_text(
        "---\nname: deploy-notes\ndescription: how the demo-app deploy runs\n---\n\nbody\n",
        encoding="utf-8")

    handle_slash("/memory list", _State(), config)

    out = capsys.readouterr().out
    assert "deploy-notes" in out


def test_unknown_subcommand_is_reported_not_swallowed(config, capsys):
    handle_slash("/mcp wibble", _State(), config)
    assert "Unknown /mcp subcommand" in "".join(capsys.readouterr())
