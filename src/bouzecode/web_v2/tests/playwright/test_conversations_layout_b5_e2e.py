# [desc] Mise en page de /conversations mesurée en pixels réels : composer, onglets, cartes. [/desc]
"""Mise en page de la page Conversations, mesurée dans un vrai navigateur.

POURQUOI UN NAVIGATEUR EST INDISPENSABLE ICI : tous les critères de ce fichier sont
des grandeurs que seul un moteur de rendu produit — `display` calculé après cascade,
position et largeur en pixels après mise en page (flexbox), luminance d'une couleur
de fond résolue depuis des variables CSS. Rien de tout cela n'existe dans la réponse
HTTP, et happy-dom ne calcule aucune géométrie.

Ce qui NE demandait pas de navigateur a été redescendu au client de test Flask :
la présence du composer et l'absence du bouton "+" se lisent dans le HTML rendu
(voir `tests/test_conversations_layout.py`).
"""
from __future__ import annotations

from pathlib import Path

import pytest

_SHOT_DIR = Path(__file__).parent / "_artifacts"

# Le violet accent de l'app, #7c3aed, tel que le navigateur le rend.
_ACCENT_RGB = "124, 58, 237"


def _computed_display(page, selector: str) -> str:
    return page.evaluate(
        "sel => { const el = document.querySelector(sel);"
        " return el ? getComputedStyle(el).display : '__absent__'; }",
        selector,
    )


def _open_conversations(page, server: str):
    page.goto(f"{server}/conversations", wait_until="domcontentloaded")
    page.wait_for_selector(".conv-main")


def test_the_prompt_bar_stays_visible_once_a_tab_is_open(server, page):
    """La barre de prompt reste visible à l'écran, à l'accueil comme avec un onglet ouvert."""
    _SHOT_DIR.mkdir(parents=True, exist_ok=True)
    _open_conversations(page, server)

    # Accueil : aucun onglet ouvert.
    at_home = page.evaluate(
        "() => document.querySelector('.conv-main').classList.contains('tabs-open')"
    )
    assert at_home is False, "au chargement, aucun onglet ne doit être marqué ouvert"
    assert _computed_display(page, "#conv-new-bar") != "none", (
        "la barre de prompt doit être visible à l'accueil"
    )
    page.screenshot(path=str(_SHOT_DIR / "prompt_bar_home.png"))

    # Onglet ouvert : la classe est posée directement pour éprouver la RÈGLE CSS
    # (le JS qui la pose est couvert par le test DOM conversations.b5.test.js).
    page.evaluate("() => document.querySelector('.conv-main').classList.add('tabs-open')")

    assert _computed_display(page, "#conv-new-bar") != "none", (
        "la barre de prompt doit RESTER visible quand un onglet est ouvert"
    )
    page.screenshot(path=str(_SHOT_DIR / "prompt_bar_tab_open.png"))


def test_the_send_button_sits_on_the_same_line_as_the_prompt(server, page):
    """Le bouton d'envoi est à droite du champ, sur la même ligne, et la barre occupe
    toute la largeur de la zone de lecture."""
    _SHOT_DIR.mkdir(parents=True, exist_ok=True)
    _open_conversations(page, server)
    page.wait_for_selector("#conv-new-bar")

    rects = page.evaluate(
        """() => {
            const q = sel => { const el = document.querySelector(sel);
                if (!el) return null;
                const x = el.getBoundingClientRect();
                return { top: x.top, bottom: x.bottom, left: x.left,
                         right: x.right, width: x.width, height: x.height };
            };
            return { form: q('#conv-new-bar'), input: q('#conv-new-input'),
                     send: q('#conv-new-send'), main: q('.conv-main') };
        }"""
    )
    for name, rect in rects.items():
        assert rect, f"élément {name} introuvable dans la page"

    assert rects["send"]["top"] < rects["input"]["bottom"], (
        f"le bouton d'envoi doit être sur la même ligne que le champ "
        f"(bouton.top={rects['send']['top']:.1f} >= champ.bottom={rects['input']['bottom']:.1f})"
    )
    assert rects["send"]["left"] >= rects["input"]["right"] - 1, (
        f"le bouton d'envoi doit être à droite du champ, pas dessous "
        f"(bouton.left={rects['send']['left']:.1f} < champ.right={rects['input']['right']:.1f})"
    )

    width_ratio = rects["form"]["width"] / rects["main"]["width"]
    assert width_ratio >= 0.95, (
        f"la barre ({rects['form']['width']:.1f}px) doit occuper au moins 95% de la zone "
        f"de lecture ({rects['main']['width']:.1f}px), ratio mesuré {width_ratio:.3f}"
    )

    page.screenshot(path=str(_SHOT_DIR / "prompt_bar_layout.png"))


# Luminance relative WCAG du fond calculé d'un élément — sert à mesurer un contraste.
_RELATIVE_LUMINANCE = """
sel => {
  const el = document.querySelector(sel);
  if (!el) return null;
  const bg = getComputedStyle(el).backgroundColor;
  const m = bg.match(/rgba?\\(([^)]+)\\)/);
  if (!m) return null;
  const [r, g, b] = m[1].split(',').map(Number);
  const lin = c => { c /= 255; return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4); };
  return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
}
"""


def _open_first_conversation(page, ready_selector: str) -> bool:
    """Clique la 1re conversation de la barre latérale ; False si le poste n'en a aucune."""
    item = page.query_selector(".conv-item")
    if item is None:
        return False
    item.click()
    try:
        page.wait_for_selector(ready_selector, timeout=8000)
        return True
    except Exception:  # noqa: BLE001 — rien de rendu (conversation vide)
        return False


def test_message_cards_stand_out_from_the_reading_panel(server, page):
    """Une carte de message se détache du panneau de lecture : fond plus clair, bordure et ombre."""
    _SHOT_DIR.mkdir(parents=True, exist_ok=True)
    _open_conversations(page, server)

    if not _open_first_conversation(page, ".conv-messages .pui-bubble"):
        pytest.skip("aucune conversation avec message rendu sur ce poste — rien à mesurer")

    card = page.evaluate(_RELATIVE_LUMINANCE, ".conv-messages .pui-bubble")
    panel = page.evaluate(_RELATIVE_LUMINANCE, ".conv-panels")
    body = page.evaluate(_RELATIVE_LUMINANCE, "body")
    assert card is not None, "carte de message introuvable"
    assert panel is not None, "panneau de lecture introuvable"

    contrast = (card + 0.05) / (panel + 0.05)
    assert contrast >= 1.3, (
        f"la carte doit se détacher du panneau (contraste mesuré {contrast:.3f} < 1.3) — "
        f"luminance carte={card:.5f} panneau={panel:.5f}"
    )
    if body is not None:
        assert abs(panel - body) > 1e-4, "le panneau de lecture doit se distinguer du fond de page"

    box = page.evaluate(
        "sel => { const s = getComputedStyle(document.querySelector(sel));"
        " return { border: s.borderTopWidth, shadow: s.boxShadow }; }",
        ".conv-messages .pui-bubble",
    )
    assert box["border"] == "1px", f"bordure de carte attendue à 1px, obtenu {box['border']}"
    assert box["shadow"] and box["shadow"] != "none", "une ombre courte est attendue sur la carte"

    page.screenshot(path=str(_SHOT_DIR / "message_card_contrast.png"))


def test_opening_a_conversation_highlights_exactly_one_tab_and_one_sidebar_item(server, page):
    """Ouvrir une conversation souligne l'onglet actif en accent, tronque son titre trop
    long, et ne laisse qu'une seule entrée surlignée dans la barre latérale."""
    _SHOT_DIR.mkdir(parents=True, exist_ok=True)
    _open_conversations(page, server)

    if not _open_first_conversation(page, ".conv-tab.active"):
        pytest.skip("aucune conversation sur ce poste — pas d'onglet à ouvrir")

    styles = page.evaluate(
        """() => {
            const tab = document.querySelector('.conv-tab.active');
            const title = tab.querySelector('.conv-tab-title');
            const tabs = document.querySelector('.conv-tabs');
            const st = getComputedStyle(tab);
            const stt = title ? getComputedStyle(title) : {};
            const sts = getComputedStyle(tabs);
            return {
                maxWidth: st.maxWidth,
                accentBarWidth: st.borderTopWidth,
                accentBarColor: st.borderTopColor,
                titleOverflow: stt.overflow,
                titleTextOverflow: stt.textOverflow,
                sideFade: sts.maskImage || sts.webkitMaskImage,
                highlightedSidebarItems: document.querySelectorAll('.conv-item.active').length,
            };
        }"""
    )

    assert styles["maxWidth"] == "220px", f"largeur max d'onglet attendue 220px, obtenu {styles['maxWidth']}"
    assert styles["accentBarWidth"] == "2px", (
        f"trait de l'onglet actif attendu à 2px, obtenu {styles['accentBarWidth']}"
    )
    assert _ACCENT_RGB in styles["accentBarColor"], (
        f"le trait de l'onglet actif doit être en accent, obtenu {styles['accentBarColor']}"
    )
    assert styles["titleOverflow"] == "hidden", "un titre trop long doit être tronqué"
    assert styles["titleTextOverflow"] == "ellipsis", "un titre tronqué doit finir par des points de suspension"
    assert styles["sideFade"] and styles["sideFade"] != "none", (
        "la bande d'onglets doit s'estomper sur les côtés (mask-image)"
    )
    assert styles["highlightedSidebarItems"] == 1, (
        f"exactement 1 entrée de la barre latérale doit être surlignée, "
        f"obtenu {styles['highlightedSidebarItems']}"
    )

    page.screenshot(path=str(_SHOT_DIR / "active_tab_and_sidebar.png"))
