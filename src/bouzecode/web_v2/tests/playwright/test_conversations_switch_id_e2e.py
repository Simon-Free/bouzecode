# [desc] Le switch Conversation/Récap est intégré à la ligne meta et l'id court n'apparaît qu'une fois. [/desc]
"""Switch [Conversation | Récap] : placement, contraste, et unicité de l'identifiant.

POURQUOI UN NAVIGATEUR EST INDISPENSABLE ICI : le panneau n'existe qu'APRÈS un vrai
clic sur une conversation de la barre latérale — c'est le JavaScript qui le construit,
il n'est nulle part dans le HTML servi. Et le critère « le bouton actif est
visiblement contrasté » se mesure sur le `background-color` CALCULÉ par le moteur de
rendu, pas dans la feuille de style.

Le smoke de boot qui vivait aussi dans ce fichier a été fusionné dans
test_pages_boot_smoke.py (il était identique dans quatre fichiers).
"""
from __future__ import annotations

from pathlib import Path

import pytest

_SHOT_DIR = Path(__file__).parent / "_artifacts"

# Le violet accent de l'app, #7c3aed, tel que le navigateur le rend.
_ACCENT_RGB = "124, 58, 237"

_READ_PANEL_LAYOUT = """() => {
    const panel = document.querySelector('.conv-panel:not([hidden])');
    const status = panel.querySelector('.conv-panel-status');
    const sw = status ? status.querySelector('.conv-view-switch') : null;
    const activeBtn = sw ? sw.querySelector('.conv-view-btn.active') : null;
    return {
        switchIsInMetaRow: !!sw && sw.parentElement === status,
        switchHasItsOwnRow: [...panel.querySelectorAll('.conv-view-switch')]
            .some(s => s.parentElement === panel),
        activeButtonBackground: activeBtn ? getComputedStyle(activeBtn).backgroundColor : null,
        idChipsInPanel: panel.querySelectorAll('.conv-meta-id').length,
        idChipsInTabs: document.querySelectorAll('#conv-tabs .conv-tab-id').length,
    };
}"""


def _open_first_conversation(page) -> bool:
    """Clique la 1re conversation de la barre latérale ; False si le poste n'en a aucune."""
    item = page.query_selector(".conv-item")
    if item is None:
        return False
    item.click()
    try:
        page.wait_for_selector(".conv-panel:not([hidden]) .conv-panel-status", timeout=8000)
        return True
    except Exception:  # noqa: BLE001 — panneau jamais rendu
        return False


def test_opening_a_conversation_shows_one_compact_switch_and_one_id(server, page):
    """Ouvrir une conversation affiche le switch sur la ligne meta, son bouton actif
    coloré, et l'identifiant court une seule fois."""
    _SHOT_DIR.mkdir(parents=True, exist_ok=True)
    page.goto(f"{server}/conversations", wait_until="domcontentloaded")
    page.wait_for_selector(".conv-main")

    if not _open_first_conversation(page):
        pytest.skip("aucune conversation sur ce poste — pas de panneau à mesurer")

    layout = page.evaluate(_READ_PANEL_LAYOUT)

    assert layout["switchIsInMetaRow"], "le switch doit être posé sur la ligne meta du panneau"
    assert not layout["switchHasItsOwnRow"], "le switch ne doit plus occuper une ligne à lui seul"
    assert layout["activeButtonBackground"] and _ACCENT_RGB in layout["activeButtonBackground"], (
        f"le bouton actif doit être coloré en accent, obtenu {layout['activeButtonBackground']}"
    )
    assert layout["idChipsInPanel"] == 1, (
        f"l'identifiant court doit apparaître une seule fois, obtenu {layout['idChipsInPanel']}"
    )
    assert layout["idChipsInTabs"] == 0, (
        f"l'identifiant ne doit plus être répété dans les onglets, obtenu {layout['idChipsInTabs']}"
    )

    page.screenshot(path=str(_SHOT_DIR / "switch_in_meta_row.png"))
