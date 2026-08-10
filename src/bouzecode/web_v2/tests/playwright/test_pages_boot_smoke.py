# [desc] Smoke navigateur unique : les pages de l'app se chargent sans aucune erreur JavaScript. [/desc]
"""Le seul smoke de boot de web_v2 — il était recopié dans 4 fichiers Playwright.

POURQUOI UN NAVIGATEUR EST INDISPENSABLE ICI : le client de test Flask reçoit du
HTML, il n'EXÉCUTE pas les `<script>`. Une SyntaxError, un export renommé ou un
global disparu laisse la réponse HTTP parfaitement à 200 alors que la page est
figée pour l'utilisateur. Les tests vitest ne l'attrapent pas non plus : ils
importent le module en ESM au lieu de laisser la page le charger comme le fait le
template (`<script type="module">` pour /conversations, `<script src>` classique
pour /agent-builder). Seul un vrai navigateur qui charge la vraie page le prouve.
"""
from __future__ import annotations

import pytest

# /conversations poll /api/agents/tree en continu : `networkidle` n'est jamais
# atteint et flake en timeout. On attend un repère du DOM rendu à la place.
PAGES = [
    pytest.param("/conversations", "#conv-list", id="conversations"),
    pytest.param("/agent-builder", "#b-prompt", id="agent-builder"),
]


@pytest.mark.parametrize(("path", "ready_selector"), PAGES)
def test_page_loads_without_any_javascript_error(server, page_with_console_errors, path, ready_selector):
    """Ouvrir la page dans un navigateur ne produit aucune erreur console ni pageerror."""
    page, errors = page_with_console_errors

    page.goto(f"{server}{path}", wait_until="domcontentloaded")
    page.wait_for_selector(ready_selector, timeout=15000)
    # Laisse le premier rendu et le premier poll s'exécuter : une erreur d'init
    # arrive souvent après le premier fetch, pas au parse.
    page.wait_for_timeout(1500)

    assert errors == [], f"erreurs JavaScript au chargement de {path} : {errors}"
