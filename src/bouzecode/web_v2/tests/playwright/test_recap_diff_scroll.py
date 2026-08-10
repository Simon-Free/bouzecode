# [desc] Les zones de diff du récap sont réellement scrollables (CSS calculé par le navigateur). [/desc]
"""Zones de diff side-by-side du récap : bornées en hauteur ET scrollables.

POURQUOI UN NAVIGATEUR EST INDISPENSABLE ICI : la question posée est « est-ce que
l'utilisateur peut faire défiler ce bloc ? ». Elle se joue entièrement dans le moteur
de rendu — cascade CSS, `max-height: 60vh` résolu contre la hauteur du viewport,
`overflow-y` calculé, `scrollHeight` mesuré après mise en page. Le client de test
Flask ne voit qu'une feuille de style servie en texte ; happy-dom ne calcule pas de
hauteur. Le bug d'origine était exactement de ce type : un `max-height` sans
`overflow`, HTTP parfaitement vert, zone figée à l'écran.

Le test part du vrai `pages.css` servi par l'app à chaque exécution (donc immunisé au
cache navigateur), y injecte un diff plus haut que la zone, et lit les métriques.
"""
from __future__ import annotations

# Reproduit la structure DOM réelle du récap
# (details.recap-diff > .recap-diff-content > .recap-sxs > .sxs-row) avec assez de
# lignes pour dépasser 60vh, puis renvoie les métriques de défilement.
_INJECT_LONG_DIFF = r"""
() => {
  const details = document.createElement('details');
  details.className = 'recap-diff';
  details.open = true;
  const body = document.createElement('div');
  body.className = 'recap-diff-content';
  const grid = document.createElement('div');
  grid.className = 'recap-sxs';
  for (let i = 0; i < 250; i++) {
    const row = document.createElement('div');
    row.className = 'sxs-row sxs-eq';
    row.innerHTML =
      '<div class="sxs-num">' + (i + 1) + '</div>' +
      '<div class="sxs-code">const line' + i + ' = ' + i + ';</div>' +
      '<div class="sxs-num">' + (i + 1) + '</div>' +
      '<div class="sxs-code">const line' + i + ' = ' + i + ';</div>';
    grid.appendChild(row);
  }
  body.appendChild(grid);
  details.appendChild(body);
  document.body.appendChild(details);
  const cs = getComputedStyle(body);
  return {
    overflowY: cs.overflowY,
    maxHeight: cs.maxHeight,
    scrollHeight: body.scrollHeight,
    clientHeight: body.clientHeight,
  };
}
"""


def test_a_long_diff_can_be_scrolled_inside_its_zone(server, page):
    """Un diff plus long que sa zone reste dans une zone bornée, avec une barre de défilement."""
    # /conversations charge le vrai pages.css servi par l'app.
    page.goto(f"{server}/conversations", wait_until="domcontentloaded")
    page.wait_for_selector("#conv-list", timeout=15000)

    metrics = page.evaluate(_INJECT_LONG_DIFF)

    assert metrics["overflowY"] == "auto", (
        f"overflow-y attendu 'auto', obtenu {metrics['overflowY']!r} — "
        "la règle .recap-diff-content{overflow:auto} n'est pas appliquée"
    )
    assert metrics["maxHeight"] != "none", (
        f"la zone doit être bornée en hauteur, max-height obtenu {metrics['maxHeight']!r}"
    )
    assert metrics["scrollHeight"] > metrics["clientHeight"], (
        f"le contenu ne déborde pas : scrollHeight={metrics['scrollHeight']} "
        f"clientHeight={metrics['clientHeight']} — rien à faire défiler"
    )
