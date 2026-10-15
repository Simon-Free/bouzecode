"""EnableChromeDevtools sur une machine SANS Google Chrome.

Constaté le 2026-09-24 : un agent DeepSeek a déclaré la vérification navigateur « impossible »
(deux échecs « See logs ») sur une machine qui n'avait que Firefox et le Chromium de Playwright.
Ce que ces tests verrouillent :
- sans Chrome, le Chromium de Playwright est trouvé et passé en `--executablePath` ;
- sans aucun navigateur, AUCUN lancement : un message qui dit quoi installer, et où ;
- npx s'exécute sans question interactive (`npm_config_yes`) ;
- un démarrage raté rend la sortie d'erreur et l'action à mener (ex. Node trop ancien).
Aucun vrai navigateur ni vrai npx : faux transport et résolveurs injectés.
"""
import os

import pytest

from bouzecode.backend.chrome_devtools import launcher
from bouzecode.backend.core import tool_registry

#  Capturée avant que la fixture ne la remplace : le test « sans npx » l'exerce pour de vrai.
_VRAI_MANQUE = launcher._manque_pour_demarrer


class FauxTransport:
    CREES = []
    ECHEC = None  # texte de stderr si le démarrage doit échouer

    def __init__(self, config):
        self.config = config
        self.arrete = False
        self.stderr_output = FauxTransport.ECHEC or ""
        FauxTransport.CREES.append(self)

    def start(self):
        pass

    def request(self, method, params=None, timeout=None):
        if FauxTransport.ECHEC:
            raise TimeoutError("MCP server 'chrome-devtools' timed out on 'initialize'")
        if method == "tools/list":
            return {"tools": [{"name": "navigate", "description": "va a une URL"}]}
        return {}

    def notify(self, method, params=None):
        pass

    def stop(self):
        self.arrete = True

    @property
    def alive(self):
        return not self.arrete


@pytest.fixture(autouse=True)
def _isolation(tmp_path, monkeypatch):
    launcher.shutdown_all()
    FauxTransport.CREES, FauxTransport.ECHEC = [], None
    monkeypatch.setattr(launcher, "StdioTransport", FauxTransport)
    monkeypatch.setattr(launcher, "_manifest_path", lambda: tmp_path / "manifeste.json")
    monkeypatch.setattr(launcher, "_manque_pour_demarrer", lambda command: None)
    os.environ.pop("BOUZECODE_ENABLE_CHROME_DEVTOOLS", None)
    yield
    launcher.shutdown_all()
    for nom in ("mcp__chrome-devtools__navigate",):
        try:
            tool_registry.unregister_tool(nom)
        except Exception:
            pass


def _faux_chromium_playwright(dossier):
    binaire = dossier / "chromium-1243" / "chrome-linux64" / "chrome"
    binaire.parent.mkdir(parents=True)
    binaire.write_text("#!/bin/sh\n")
    return binaire


def test_sans_chrome_le_chromium_de_playwright_est_utilise(tmp_path, monkeypatch):
    binaire = _faux_chromium_playwright(tmp_path / "ms-playwright")
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path / "ms-playwright"))
    monkeypatch.setattr(launcher, "chrome_installe", lambda: False)
    monkeypatch.setattr("shutil.which", lambda nom: None)

    message = launcher.enable_chrome_devtools()

    assert "activated" in message
    args = FauxTransport.CREES[-1].config.args
    assert args[args.index("--executablePath") + 1] == str(binaire)
    assert "--headless" in args and "--isolated" in args
    assert "--chromeArg=--no-sandbox" in args  # sinon plantage au démarrage (userns restreints)


def test_sans_aucun_navigateur_rien_n_est_lance_et_le_message_dit_quoi_installer(
        tmp_path, monkeypatch):
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path / "vide"))
    monkeypatch.setattr(launcher, "chrome_installe", lambda: False)
    monkeypatch.setattr(launcher, "chromium_de_secours", lambda: None)

    message = launcher.enable_chrome_devtools()

    assert FauxTransport.CREES == []
    assert "playwright install chromium" in message
    assert "ENVIRONNEMENT DU PROJET" in message


def test_npx_s_execute_sans_question_interactive(monkeypatch):
    monkeypatch.setattr(launcher, "chrome_installe", lambda: True)
    launcher.enable_chrome_devtools()
    assert FauxTransport.CREES[-1].config.env.get("npm_config_yes") == "true"


def test_npx_reutilise_le_paquet_en_cache_sans_interroger_le_registre(monkeypatch):
    # Version figée (MCP_VERSION) : une version npm publiée est immuable, le cache suffit.
    # Sans prefer-offline, npx interrogeait le registre à chaque lancement (~36 s mesurées),
    # au-delà du délai de 30 s de 'initialize'.
    monkeypatch.setattr(launcher, "chrome_installe", lambda: True)
    launcher.enable_chrome_devtools()
    assert FauxTransport.CREES[-1].config.env.get("npm_config_prefer_offline") == "true"


def test_un_demarrage_rate_rend_la_sortie_d_erreur_et_l_action(monkeypatch):
    monkeypatch.setattr(launcher, "chrome_installe", lambda: True)
    FauxTransport.ECHEC = ("ERROR: `chrome-devtools-mcp` does not support Node v22.11.0. "
                           "Please upgrade to Node 22.12.0 LTS or a newer LTS.")

    message = launcher.enable_chrome_devtools()

    assert "does not support Node v22.11.0" in message
    assert "Node >= 22.12" in message
    assert "See logs" not in message


def test_sans_npx_le_message_dit_d_installer_node(monkeypatch):
    monkeypatch.setattr(launcher, "_manque_pour_demarrer", _VRAI_MANQUE)
    monkeypatch.setattr("shutil.which", lambda nom: None)
    monkeypatch.setattr(launcher, "chrome_installe", lambda: True)

    message = launcher.enable_chrome_devtools()

    assert FauxTransport.CREES == []
    assert "Node" in message and "npx" in message
