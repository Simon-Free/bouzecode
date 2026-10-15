# [desc] Après /clear, la nouvelle conversation ne porte plus les outils navigateur activés par la précédente, Chrome est arrêté, et la reprise de l'ancienne session les retrouve. [/desc]
"""Session 2fa7d817 (2026-10-07) : chrome-devtools activé au tour 12, puis `/clear`. La session
suivante (d407d73d) n'ouvre jamais le navigateur mais relit à chacun de ses 27 appels les 30
outils du manifeste (préfixe 32,4 k tokens au lieu de ≈ 20 k) ; son JSON dit
`outils_navigateur: true`.

`mock_llm` remplace la liste d'outils envoyée par [] : on observe donc la liste que le harnais
ENVERRAIT (`get_tool_schemas`) et le JSON de session, les deux faces du constat."""
import json
import sys
import threading
from pathlib import Path

import pytest

from bouzecode.backend.agent.state import AgentState
from bouzecode.backend.chrome_devtools import launcher
from bouzecode.backend.commands.core.basic import cmd_clear
from bouzecode.backend.commands.session.session import _build_session_data
from bouzecode.backend.commands.session.session_pick import restore_state
from bouzecode.backend.core import tool_registry
from tests.e2e_harness import bouzecode
from tests.fake_llm import MockLLM

FAKE_SERVER = str(Path(__file__).parent / "fake_mcp_server.py")
NAV_TOOL = "mcp__chrome-devtools__navigate"
METH = '<tool_use name="Methodology" id="m1"><param name="content">ok</param></tool_use>'


@pytest.fixture(autouse=True)
def _navigateur_isole(tmp_path, monkeypatch):
    """Manifeste et sessions dans tmp_path ; aucun serveur ni outil d'un autre test."""
    monkeypatch.setattr(launcher, "_manifest_path",
                        lambda: tmp_path / "chrome_devtools_manifest.json")
    monkeypatch.setattr("bouzecode.backend.core.config.DAILY_DIR", tmp_path / "daily")
    monkeypatch.setattr("bouzecode.backend.core.config.SESSION_HIST_FILE",
                        tmp_path / "history.json")
    monkeypatch.delenv("BOUZECODE_ENABLE_CHROME_DEVTOOLS", raising=False)
    launcher.shutdown_all()
    yield
    launcher.shutdown_all()


def _outils_envoyes() -> list[str]:
    return [schema["name"] for schema in tool_registry.get_tool_schemas()]


def _conversation_qui_a_allume_le_navigateur():
    """L'agent active chrome-devtools (vrai serveur MCP de test), puis la conversation se clôt."""
    message = launcher.enable_chrome_devtools(command=sys.executable, args=[FAKE_SERVER])
    assert "activated" in message
    return bouzecode(["vérifie la page"], mock_llm=MockLLM([METH, "C'est vérifié."]))


def _session_close_enregistree(dossier: Path) -> dict:
    (fichier,) = dossier.rglob("session_*.json")
    return json.loads(fichier.read_text(encoding="utf-8"))


def test_apres_clear_la_nouvelle_conversation_n_a_plus_les_outils_navigateur(tmp_path):
    """La nouvelle conversation part sans les outils, et son JSON dit outils_navigateur=false."""
    state = _conversation_qui_a_allume_le_navigateur().state
    assert NAV_TOOL in _outils_envoyes()

    cmd_clear("", state, {"model": "test", "_session_id": "2fa7d817"})

    assert NAV_TOOL not in _outils_envoyes()
    nouvelle = _build_session_data(state, session_id="d407d73d", model="m")
    assert nouvelle[launcher.CLE_SESSION] is False
    #  La session close, elle, a été enregistrée AVEC ses outils : une reprise les retrouvera.
    assert _session_close_enregistree(tmp_path / "daily")[launcher.CLE_SESSION] is True


def test_clear_arrete_le_chrome_de_la_conversation_close():
    """Pas de Chrome orphelin : le serveur MCP allumé avant /clear est arrêté."""
    _conversation_qui_a_allume_le_navigateur()
    transport = launcher._TRANSPORTS[threading.get_ident()]
    assert transport.alive

    cmd_clear("", AgentState(), {"model": "test"})

    assert not transport.alive
    assert not launcher.is_active()


def test_enable_chrome_devtools_remet_les_outils_apres_clear():
    """La nouvelle conversation peut rallumer le navigateur elle-même."""
    _conversation_qui_a_allume_le_navigateur()
    cmd_clear("", AgentState(), {"model": "test"})

    launcher.enable_chrome_devtools(command=sys.executable, args=[FAKE_SERVER])

    assert NAV_TOOL in _outils_envoyes()


def test_reprendre_la_session_close_apres_clear_retrouve_ses_outils(tmp_path):
    """Reprise de l'ancienne session : même liste d'outils qu'à son dernier appel (cache)."""
    state = _conversation_qui_a_allume_le_navigateur().state
    avant = _outils_envoyes()
    cmd_clear("", state, {"model": "test", "_session_id": "2fa7d817"})
    assert NAV_TOOL not in _outils_envoyes()

    restore_state(AgentState(), _session_close_enregistree(tmp_path / "daily"))

    assert _outils_envoyes() == avant


def test_capacite_declaree_pour_le_process_les_outils_restent_apres_clear(monkeypatch):
    """Lancé avec --enable-chrome-devtools, un démarrage les déclarerait : /clear les garde."""
    _conversation_qui_a_allume_le_navigateur()
    monkeypatch.setenv("BOUZECODE_ENABLE_CHROME_DEVTOOLS", "1")

    cmd_clear("", AgentState(), {"model": "test"})

    assert NAV_TOOL in _outils_envoyes()
    assert not launcher.is_active(), "Chrome arrêté quand même : il se rallume à l'usage"
