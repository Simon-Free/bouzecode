# [desc] profil serveur (BOUZECODE_SERVER_PROFILE / BOUZECODE_DENIED_TOOLS) : ni outils web, ni Bash, ni MCP, quel que soit le profil d'agent. [/desc]
"""Le process bouzecode d'une application hébergée ne doit ni sortir sur Internet ni
exécuter de commande, quel que soit le profil chargé (un profil introuvable ou à
`tools: []` rend tous les outils)."""
from __future__ import annotations

import pytest

from bouzecode.backend.core import tool_registry as reg

_APPELS: list = []


def _outil(name: str, read_only: bool = False) -> reg.ToolDef:
    return reg.ToolDef(
        name=name,
        schema={"name": name, "description": "outil de test",
                "input_schema": {"type": "object", "properties": {"x": {"type": "string"}},
                                 "required": ["x"]}},
        func=lambda params, config: _APPELS.append((name, params["x"])) or f"ok:{params['x']}",
        read_only=read_only,
    )


@pytest.fixture(autouse=True)
def _outils(monkeypatch):
    monkeypatch.delenv(reg.SERVER_PROFILE_ENV, raising=False)
    monkeypatch.delenv(reg.DENIED_TOOLS_ENV, raising=False)
    _APPELS.clear()
    reg.push_local_overlay()
    for name in ("Bash", "WebFetch", "mcp__chrome-devtools__navigate", "Read", "ZzLecture"):
        reg.register_tool(_outil(name, read_only=(name in ("Read", "ZzLecture"))))
    yield
    reg.pop_local_overlay()


def _annonces() -> set:
    return {s["name"] for s in reg.get_tool_schemas()}


def test_sans_profil_serveur_rien_ne_change():
    assert {"Bash", "WebFetch", "Read"} <= _annonces()
    assert reg.execute_tool("Bash", {"x": "ls"}, {}) == "ok:ls"


def test_profil_serveur_retire_web_bash_et_mcp(monkeypatch):
    monkeypatch.setenv(reg.SERVER_PROFILE_ENV, "1")
    annonces = _annonces()
    assert not {"Bash", "WebFetch", "mcp__chrome-devtools__navigate"} & annonces
    assert "Read" in annonces
    for name in ("Bash", "WebFetch", "mcp__chrome-devtools__navigate"):
        resultat = reg.execute_tool(name, {"x": "1"}, {})
        assert "interdit sur ce serveur" in resultat and reg.SERVER_PROFILE_ENV in resultat
        assert not reg.is_enabled(name)
    assert _APPELS == []
    # Réactiver l'outil ne lève pas l'interdiction.
    reg.enable_tool("Bash")
    assert "interdit" in reg.execute_tool("Bash", {"x": "ls"}, {})
    assert reg.execute_tool("Read", {"x": "f"}, {}) == "ok:f"


def test_liste_explicite_avec_motif(monkeypatch):
    monkeypatch.setenv(reg.DENIED_TOOLS_ENV, "Zz*, Read")
    assert "interdit" in reg.execute_tool("ZzLecture", {"x": "1"}, {})
    assert "interdit" in reg.execute_tool("Read", {"x": "1"}, {})
    assert reg.execute_tool("Bash", {"x": "ls"}, {}) == "ok:ls"
