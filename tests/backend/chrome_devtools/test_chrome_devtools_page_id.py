"""`pageId` obligatoire depuis chrome-devtools-mcp 1.8.0 : le harnais le fournit lui-même.

CONSTATÉ LE 2026-09-26 avec le vrai paquet (headless, `tools/list` en JSON-RPC stdio) :
- jusqu'à 1.7.0, `navigate_page` et `take_snapshot` n'ont pas de `pageId` et REFUSENT l'argument
  (« Unknown argument for tool "navigate_page": "pageId" … Remove it and retry. ») ;
- à partir de 1.8.0 (jusqu'à 1.10.1, la dernière), 28 des 30 outils exigent `pageId` (un NOMBRE,
  l'indice affiché par `list_pages` : « 2: Titre (url) [selected] ») ; sans lui :
  « Input validation error: … pageId: Invalid input: expected number, received undefined » ;
  en chaîne (« 2 », ce que rend le protocole XML) : « expected number, received string ».
Avec `chrome-devtools-mcp@latest`, tout `navigate_page` / `take_snapshot` sans `pageId` échouait.

Ce que ces tests verrouillent (aucun vrai Chrome ni npx : faux transport) :
- le paquet est ÉPINGLÉ sur une version testée, jamais `@latest` ;
- `pageId` absent alors que le schéma DU SERVEUR EN COURS l'exige → celui de la page
  sélectionnée (lu par `list_pages`) est injecté ; `pageId` fourni → respecté (converti en nombre) ;
- serveur ancien sans `pageId` dans son schéma → l'argument est retiré au lieu d'être refusé ;
- le schéma annoncé au modèle ne rend plus `pageId` obligatoire (le harnais le complète).
"""
import os
import re
import threading

import pytest

from bouzecode.backend.chrome_devtools import launcher
from bouzecode.backend.core import tool_registry

#  Les vrais, avant tout monkeypatch (test réel) ; le manifeste reste dans tmp_path.
_VRAIS = {nom: getattr(launcher, nom)
          for nom in ("StdioTransport", "chrome_installe", "_manque_pour_demarrer")}

SNAP_TOOL = "mcp__chrome-devtools__take_snapshot"
NAV_TOOL = "mcp__chrome-devtools__navigate_page"

LISTE_PAGES = "## Pages\n1: about:blank\n2: Deux (data:text/html,<p>B</p>) [selected]"


def _schema(proprietes, requis):
    return {"type": "object", "properties": {p: {"type": "number" if p == "pageId" else "string"}
                                             for p in proprietes}, "required": requis}


OUTILS_RECENTS = [  # forme de chrome-devtools-mcp >= 1.8.0
    {"name": "list_pages", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "navigate_page", "inputSchema": _schema(["pageId", "type", "url"], ["pageId"])},
    {"name": "take_snapshot", "inputSchema": _schema(["pageId", "verbose"], ["pageId"])},
]
OUTILS_ANCIENS = [  # forme de chrome-devtools-mcp <= 1.7.0
    {"name": "list_pages", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "navigate_page", "inputSchema": _schema(["type", "url"], [])},
    {"name": "take_snapshot", "inputSchema": _schema(["verbose"], [])},
]


class FauxTransport:
    """Mémorise chaque `tools/call` ; `list_pages` rend `LISTE_PAGES`."""

    CREES = []
    OUTILS = OUTILS_RECENTS

    def __init__(self, config):
        self.config = config
        self.arrete = False
        self.appels = []
        FauxTransport.CREES.append(self)

    def start(self):
        pass

    def request(self, method, params=None, timeout=None):
        if method == "tools/list":
            return {"tools": FauxTransport.OUTILS}
        if method == "tools/call":
            self.appels.append((params["name"], dict(params["arguments"])))
            texte = LISTE_PAGES if params["name"] == "list_pages" else "ok"
            return {"content": [{"type": "text", "text": texte}]}
        return {}

    def notify(self, method, params=None):
        pass

    def stop(self):
        self.arrete = True

    @property
    def alive(self):
        return not self.arrete


def _purge_registry():
    for outil in OUTILS_RECENTS:
        try:
            tool_registry.unregister_tool(f"mcp__chrome-devtools__{outil['name']}")
        except Exception:  # noqa: BLE001 — déjà retiré
            pass


@pytest.fixture(autouse=True)
def _isolation(tmp_path, monkeypatch):
    launcher.shutdown_all()
    _purge_registry()
    FauxTransport.CREES, FauxTransport.OUTILS = [], OUTILS_RECENTS
    monkeypatch.setattr(launcher, "StdioTransport", FauxTransport)
    monkeypatch.setattr(launcher, "_manifest_path", lambda: tmp_path / "manifeste.json")
    monkeypatch.setattr(launcher, "chrome_installe", lambda: True)
    monkeypatch.setattr(launcher, "_manque_pour_demarrer", lambda command: None)
    yield
    launcher.shutdown_all()
    _purge_registry()


def _appeler(nom, params=None):
    return tool_registry.get_tool(nom).func(params or {}, {})


def _appels_serveur():
    return FauxTransport.CREES[-1].appels


def test_paquet_epingle_sur_une_version_testee():
    assert re.fullmatch(r"chrome-devtools-mcp@\d+\.\d+\.\d+", launcher.MCP_PACKAGE), \
        launcher.MCP_PACKAGE
    assert launcher.build_server_args()[0] == launcher.MCP_PACKAGE


def test_page_id_absent_injecte_celui_de_la_page_selectionnee():
    launcher.enable_chrome_devtools()
    _appeler(NAV_TOOL, {"url": "data:text/html,<h1>Salut</h1>"})
    _appeler(SNAP_TOOL)

    appels = [a for a in _appels_serveur() if a[0] != "list_pages"]
    assert appels == [("navigate_page", {"url": "data:text/html,<h1>Salut</h1>", "pageId": 2}),
                      ("take_snapshot", {"pageId": 2})]


def test_page_id_fourni_respecte_et_converti_en_nombre():
    launcher.enable_chrome_devtools()
    _appeler(SNAP_TOOL, {"pageId": "1"})

    assert _appels_serveur() == [("take_snapshot", {"pageId": 1})], \
        "aucun list_pages inutile, et le serveur refuse un pageId en chaîne"


def test_serveur_ancien_page_id_retire():
    FauxTransport.OUTILS = OUTILS_ANCIENS
    launcher.enable_chrome_devtools()
    _appeler(SNAP_TOOL, {"pageId": 2, "verbose": "true"})

    assert _appels_serveur() == [("take_snapshot", {"verbose": "true"})]


def test_schema_annonce_page_id_facultatif():
    launcher.enable_chrome_devtools()
    schema = tool_registry.get_tool(SNAP_TOOL).schema["input_schema"]

    assert "pageId" in schema["properties"], "le modèle peut toujours viser une page précise"
    assert "pageId" not in schema.get("required", [])
    assert "sélectionnée" in schema["properties"]["pageId"]["description"] \
        or "selected" in schema["properties"]["pageId"]["description"]
    assert OUTILS_RECENTS[2]["inputSchema"]["required"] == ["pageId"], \
        "le tools/list du serveur (et le manifeste) n'est pas modifié en place"


# ── Bout en bout avec le VRAI paquet (opt-in : réseau npm + un Chromium) ──────

@pytest.mark.skipif(os.environ.get("BOUZECODE_CHROME_REEL") != "1",
                    reason="vrai chrome-devtools-mcp : BOUZECODE_CHROME_REEL=1 pour le lancer")
def test_reel_navigate_puis_snapshot_sans_page_id(monkeypatch):
    import shutil
    if not shutil.which("npx"):
        pytest.skip("npx absent")
    for nom, vrai in _VRAIS.items():  # le vrai transport, le vrai détecteur de navigateur
        monkeypatch.setattr(launcher, nom, vrai)
    try:
        message = launcher.enable_chrome_devtools()  # headless + isolated par défaut
        assert "activated" in message, message
        assert "--headless" in launcher._TRANSPORT_ARGS[threading.get_ident()]
        rendu = _appeler(NAV_TOOL, {"url": "data:text/html,<h1>Salut bouzecode</h1>"})
        assert "Successfully navigated" in rendu, rendu
        snapshot = _appeler(SNAP_TOOL)
        assert 'heading "Salut bouzecode"' in snapshot, snapshot
    finally:
        launcher.shutdown_all()
