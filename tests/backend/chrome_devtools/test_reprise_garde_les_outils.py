# [desc] Une session reprise (réveil) envoie la même liste d'outils qu'à son dernier appel : les outils navigateur allumés avant la reprise sont redéclarés, sans relancer Chrome. [/desc]
"""Essai DeepSeek du 2026-09-24, racine 6bafe9cd5ee7. Réveillée au tour 45, elle repartait dans un
nouveau process sans les 30 outils chrome-devtools (liste d'outils : 59 560 → 29 706 caractères) :
tout ce qui suit les outils sortait du cache. Au tour 53 elle rappelait `EnableChromeDevtools`, la
liste regrandissait et le tour 54 ne lisait que 1 152 tokens en cache sur 42 704.

Test de frontière save/restore, comme `sessions/persistence/test_compaction_log_restore.py` : la
reprise traverse deux process, qu'une conversation `bouzecode()` ne traverse jamais."""
import sys
from pathlib import Path

import pytest

from bouzecode.backend.agent.state import AgentState
from bouzecode.backend.chrome_devtools import launcher
from bouzecode.backend.commands.session.session import _build_session_data
from bouzecode.backend.commands.session.session_pick import restore_state
from bouzecode.backend.core import tool_registry

FAKE_SERVER = str(Path(__file__).parent / "fake_mcp_server.py")
NAV_TOOL = "mcp__chrome-devtools__navigate"


@pytest.fixture(autouse=True)
def _navigateur_isole(tmp_path, monkeypatch):
    """Manifeste dans tmp_path (jamais celui du HOME) ; aucun serveur ni outil d'un autre test."""
    monkeypatch.setattr(launcher, "_manifest_path",
                        lambda: tmp_path / "chrome_devtools_manifest.json")
    monkeypatch.delenv("BOUZECODE_ENABLE_CHROME_DEVTOOLS", raising=False)
    launcher.shutdown_all()
    yield
    launcher.shutdown_all()
    try:
        tool_registry.unregister_tool(NAV_TOOL)
    except Exception:  # noqa: BLE001 — déjà retiré
        pass


def _outils_envoyes() -> list[str]:
    return [schema["name"] for schema in tool_registry.get_tool_schemas()]


def _fin_du_process() -> None:
    """Le process de l'agent s'arrête : l'atexit tue Chrome et retire les outils."""
    launcher.shutdown_all()


def test_un_agent_reveille_retrouve_les_outils_navigateur_qu_il_avait():
    """Après réveil, la liste d'outils est celle du dernier appel, et Chrome n'est pas relancé."""
    # Premier process : l'agent allume le navigateur, ses appels portent les outils chrome.
    launcher.enable_chrome_devtools(command=sys.executable, args=[FAKE_SERVER])
    avant = _outils_envoyes()
    assert NAV_TOOL in avant
    session = _build_session_data(AgentState(), session_id="s1", model="m")
    _fin_du_process()

    # Réveil : un nouveau process reprend la session.
    restore_state(AgentState(), session)

    assert _outils_envoyes() == avant
    assert not launcher.is_active(), "Chrome ne se rallume qu'à la première utilisation"


def test_un_agent_qui_avait_eteint_le_navigateur_repart_sans_ses_outils():
    """Contrôle négatif : outils retirés par DisableChromeDevtools avant la fin → pas redéclarés."""
    launcher.enable_chrome_devtools(command=sys.executable, args=[FAKE_SERVER])
    launcher.shutdown_chrome_devtools()
    avant = _outils_envoyes()
    assert NAV_TOOL not in avant
    session = _build_session_data(AgentState(), session_id="s1", model="m")
    _fin_du_process()

    restore_state(AgentState(), session)

    assert _outils_envoyes() == avant
