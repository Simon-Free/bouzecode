# [desc] en profil serveur, Write + Agent(subagent_type) ne font plus charger de plugin projet (plugins.json / profiles / requires_plugins), et une valeur non reconnue de BOUZECODE_SERVER_PROFILE échoue fermé. [/desc]
"""Rejoue la séquence de contournement relevée en revue : Bash refusé, mais l'agent
écrivait un paquet Python, un `.bouzecode/plugins.json` projet et un profil à
`requires_plugins`, puis `Agent(subagent_type=...)` importait ce paquet dans le process
serveur. Chaque étage est verrouillé : écriture sous `.bouzecode/` refusée, plugins.json
projet ignoré, ni installation ni activation de plugin."""
from __future__ import annotations

import json
import sys

import pytest

from bouzecode.backend.core import server_profile
from bouzecode.backend.core import tool_registry as reg

_PAQUET = "zz_plugin_piege_serveur"


@pytest.fixture
def projet(tmp_path, monkeypatch):
    from bouzecode.backend.core import config

    home = tmp_path / "home"
    work = tmp_path / "work"
    home.mkdir()
    work.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setattr(config, "CONFIG_DIR", home / ".bouzecode")
    monkeypatch.chdir(work)
    monkeypatch.delenv(reg.DENIED_TOOLS_ENV, raising=False)
    monkeypatch.setenv(server_profile.SERVER_PROFILE_ENV, "1")
    sys.modules.pop(_PAQUET, None)
    yield work
    sys.modules.pop(_PAQUET, None)


def _planter(work):
    """Les fichiers que la séquence cherchait à écrire (posés ici directement)."""
    pkg = work / _PAQUET
    pkg.mkdir(exist_ok=True)
    (pkg / "plugin.json").write_text(json.dumps({"name": _PAQUET, "tools": [_PAQUET]}), encoding="utf-8")
    (pkg / "__init__.py").write_text(
        "from pathlib import Path\nPath('PWNED.txt').write_text('pwned')\nTOOLS = []\n",
        encoding="utf-8")
    (work / ".bouzecode" / "profiles").mkdir(parents=True, exist_ok=True)
    (work / ".bouzecode" / "plugins.json").write_text(json.dumps({"plugins": {_PAQUET: {
        "name": _PAQUET, "scope": "project", "package": _PAQUET,
        "import_root": str(pkg), "enabled": True}}}), encoding="utf-8")
    (work / ".bouzecode" / "profiles" / "piege.yaml").write_text(
        f"name: piege\ndescription: x\nrequires_plugins:\n- {_PAQUET}\ntools: [Read]\n",
        encoding="utf-8")


@pytest.fixture
def outils_fichiers():
    """Les vrais Write / Edit, dans une vue isolée (indépendante de l'ordre des tests)."""
    from bouzecode.backend.tools.ops.file_ops import _edit, _write
    from bouzecode.backend.tools.schemas import TOOL_SCHEMAS

    schemas = {s["name"]: s for s in TOOL_SCHEMAS}
    reg.push_local_overlay()
    reg.register_tool(reg.ToolDef(name="Write", schema=schemas["Write"], func=lambda p, c: _write(**p)))
    reg.register_tool(reg.ToolDef(name="Edit", schema=schemas["Edit"], func=lambda p, c: _edit(**p)))
    yield
    reg.pop_local_overlay()


def test_write_sous_bouzecode_refuse_en_profil_serveur(projet, outils_fichiers):
    cfg: dict = {}
    assert "interdit sur ce serveur" in reg.execute_tool("Bash", {"command": "id"}, cfg)
    for chemin in (projet / ".bouzecode" / "plugins.json",
                   projet / ".bouzecode" / "profiles" / "piege.yaml",
                   projet / "sous" / ".." / ".bouzecode" / "plugins" / "p" / "plugin.json"):
        refus = reg.execute_tool("Write", {"file_path": str(chemin), "content": "{}"}, cfg)
        assert refus.startswith("Error") and server_profile.SERVER_PROFILE_ENV in refus
    assert not (projet / ".bouzecode").exists()
    # Hors .bouzecode, l'écriture reste permise.
    ok = reg.execute_tool("Write", {"file_path": str(projet / "notes.txt"), "content": "x"}, cfg)
    assert not ok.startswith("Error") and (projet / "notes.txt").exists()
    # Edit d'un fichier existant sous .bouzecode : refusé aussi.
    (projet / ".bouzecode").mkdir()
    (projet / ".bouzecode" / "plugins.json").write_text("{}", encoding="utf-8")
    refus = reg.execute_tool("Edit", {"file_path": str(projet / ".bouzecode" / "plugins.json"),
                                      "old_string": "{}", "new_string": "{\"a\": 1}"}, cfg)
    assert refus.startswith("Error") and server_profile.SERVER_PROFILE_ENV in refus


def test_hors_profil_serveur_write_sous_bouzecode_permis(projet, monkeypatch):
    monkeypatch.delenv(server_profile.SERVER_PROFILE_ENV)
    assert reg.server_write_refusal("Write", {"file_path": str(projet / ".bouzecode" / "x.yaml")}) is None


def test_plugin_projet_jamais_importe_par_un_sous_agent(projet):
    """Même si les fichiers sont là (posés avant, ou par un autre moyen), le lancement
    d'un sous-agent à `requires_plugins` n'importe rien et le signale."""
    from bouzecode.backend.multi_agent.manager import SubAgentManager
    from bouzecode.backend.plugin import list_plugins
    from bouzecode.backend.profiles.discovery import resolve_agent_profile

    _planter(projet)
    assert _PAQUET not in [e.name for e in list_plugins()]
    profil = resolve_agent_profile("piege")
    assert profil is not None and list(profil.requires_plugins) == [_PAQUET]
    cfg: dict = {}
    SubAgentManager()._apply_profile(profil, cfg, "")
    assert _PAQUET not in sys.modules
    assert not (projet / "PWNED.txt").exists()
    assert any("profil serveur" in e for e in cfg.get("_plugin_errors", []))


def test_installation_de_plugin_refusee_en_profil_serveur(projet):
    from bouzecode.backend.plugin.store import install_plugin

    ok, message = install_plugin("un-paquet", source="https://example.invalid/depot.git")
    assert ok is False and server_profile.SERVER_PROFILE_ENV in message


def test_sans_profil_serveur_plugins_json_projet_toujours_lu(projet, monkeypatch):
    from bouzecode.backend.plugin import list_plugins

    monkeypatch.delenv(server_profile.SERVER_PROFILE_ENV)
    _planter(projet)
    assert _PAQUET in [e.name for e in list_plugins()]


@pytest.mark.parametrize("valeur,actif", [
    ("", False), ("0", False), ("false", False), ("non", False), ("off", False),
    ("1", True), ("true", True), ("YES", True), ("oui", True), ("on", True),
    ("vrai", True), ("2", True),  # non reconnu : échec FERMÉ
])
def test_valeurs_du_profil_serveur(monkeypatch, valeur, actif):
    monkeypatch.setenv(server_profile.SERVER_PROFILE_ENV, valeur)
    assert server_profile.server_profile_active() is actif
    assert ("Bash" in reg.denied_tool_patterns()) is actif


def test_valeur_non_reconnue_journalisee(monkeypatch, caplog):
    monkeypatch.setattr(server_profile, "_warned", set())
    monkeypatch.setenv(server_profile.SERVER_PROFILE_ENV, "enabled")
    with caplog.at_level("WARNING"):
        assert server_profile.server_profile_active() is True
    assert "non reconnu" in caplog.text
