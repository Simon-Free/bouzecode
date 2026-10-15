"""FindCode et Tree vus par l'agent : le modèle est simulé, les outils sont réels, et le
dépôt est un vrai petit projet écrit dans tmp_path (Python + une page HTML)."""
from __future__ import annotations

import re

import pytest

from tests.e2e_harness import bouzecode
from tests.fake_llm import MockLLM

METH = '<tool_use name="Methodology" id="m{n}"><param name="content">ok</param></tool_use>'
CLOSE = "C'est fait."

SERVER = '''\
"""Petit serveur d'énigmes."""
from outils import normaliser

CHAMPS_EDITABLES = ("enonce", "solution")


def valider_champs(champs):
    """Refuse tout champ hors de CHAMPS_EDITABLES."""
    inconnus = set(champs) - set(CHAMPS_EDITABLES)
    return normaliser(sorted(inconnus))


class Handler:
    def do_POST(self):
        return valider_champs({"enonce": 1})
'''

OUTILS = '''\
def normaliser(valeurs):
    """Met les valeurs en minuscules."""
    return [v.lower() for v in valeurs]
'''

PAGE = '''\
<!doctype html>
<html><body>
<div id="carte"></div>
<script>
(function () {
  "use strict";
  var SEUIL = 120;

  // Affiche la difficulté en points de 1 à 5.
  function pointsDifficulte(niveau) {
    return "*".repeat(niveau);
  }

  function rendreCarte(e) {
    return pointsDifficulte(e.difficulte);
  }
})();
</script>
</body></html>
'''


@pytest.fixture
def depot(tmp_path):
    (tmp_path / "server.py").write_text(SERVER, encoding="utf-8")
    (tmp_path / "outils.py").write_text(OUTILS, encoding="utf-8")
    (tmp_path / "ui").mkdir()
    (tmp_path / "ui" / "page.html").write_text(PAGE, encoding="utf-8")
    return tmp_path


def _call(name: str, n: int, **params) -> str:
    body = "".join(f'<param name="{k}">{v}</param>' for k, v in params.items())
    return f'{METH.format(n=n)}\n<tool_use name="{name}" id="t{n}">{body}</tool_use>'


def _results(calls: list[tuple[str, dict]], name: str) -> list[str]:
    """Rejoue les appels, un par tour, et rend les résultats de l'outil `name`."""
    script = [_call(tool, i, **params) for i, (tool, params) in enumerate(calls)]
    result = bouzecode(["localise"], mock_llm=MockLLM(script + [CLOSE]))
    return [m["content"] for m in result.messages if m.get("role") == "tool" and m.get("name") == name]


def test_findcode_trouve_une_fonction_js_dans_le_script_d_un_html(depot):
    """Une fonction déclarée dans l'IIFE d'un <script> inline est trouvée avec sa plage exacte."""
    [out] = _results([("FindCode", {"query": "points difficulte", "path": depot})], "FindCode")
    first = out.splitlines()[1]
    assert first.startswith("1. ui/page.html:L10-12 function pointsDifficulte(niveau)")
    assert "Affiche la difficulté en points de 1 à 5." in first
    assert "called by: L15 rendreCarte" in out


def test_chaque_nom_rendu_se_relit_avec_read_symbol(depot):
    """Les noms que FindCode affiche (fonction d'un .html, constante Python) sont des
    arguments valides de Read(symbol=...)."""
    reads = _results([
        ("Read", {"file_path": depot / "ui" / "page.html", "symbol": "pointsDifficulte"}),
        ("Read", {"file_path": depot / "server.py", "symbol": "CHAMPS_EDITABLES"}),
    ], "Read")
    assert "function pointsDifficulte(niveau)" in reads[0] and "rendreCarte" not in reads[0]
    assert 'CHAMPS_EDITABLES = ("enonce", "solution")' in reads[1] and "def " not in reads[1]


def test_apres_un_edit_qui_decale_les_lignes_les_plages_suivent(depot):
    """Un Edit qui insère des lignes en tête : l'appel suivant rend les nouvelles plages."""
    outs = _results([
        ("FindCode", {"symbol": "valider_champs", "path": depot}),
        ("Edit", {"file_path": depot / "server.py", "old_string": '"""Petit serveur d\'énigmes."""',
                  "new_string": '"""Petit serveur d\'énigmes.\n\nTrois lignes de plus."""'}),
        ("FindCode", {"symbol": "valider_champs", "path": depot}),
    ], "FindCode")
    assert "server.py:L7-10 def valider_champs(champs)" in outs[0]
    assert "server.py:L9-12 def valider_champs(champs)" in outs[1]


def test_appelants_et_appeles_sont_resolus_a_travers_les_imports(depot):
    """Le voisinage d'un symbole donne qui l'appelle et ce qu'il appelle, fichier et ligne."""
    [out] = _results([("FindCode", {"symbol": "valider_champs", "path": depot})], "FindCode")
    assert re.search(r"called by:\n\s+L15 Handler\.do_POST", out)
    assert "L4 CHAMPS_EDITABLES" in out
    assert "outils.py:L1 normaliser" in out


def test_depth_2_deroule_un_niveau_de_plus(depot):
    """À depth=2, les appelants de l'appelant et les appelés de l'appelé apparaissent."""
    [out] = _results([("FindCode", {"symbol": "normaliser", "depth": 2, "path": depot})], "FindCode")
    assert "server.py:L10 valider_champs" in out
    assert "called by: server.py:L15 Handler.do_POST" in out


def test_load_true_joint_le_corps_du_meilleur_symbole(depot):
    """Localiser et lire en un seul appel : le corps du meilleur résultat est joint."""
    [out] = _results([("FindCode", {"query": "normaliser minuscules", "load": "true",
                                    "path": depot})], "FindCode")
    assert "--- outils.py :: normaliser (L1-3) ---" in out
    assert "return [v.lower() for v in valeurs]" in out
    assert "inconnus = set(champs)" not in out


def test_tree_montre_la_racine_et_ses_dossiers(depot):
    """Tree liste la racine du dépôt elle-même, avec ses fichiers et symboles principaux."""
    [out] = _results([("Tree", {"path": depot})], "Tree")
    assert "./ — 2 files — " in out and "valider_champs" in out
    assert "ui/ — 1 files — pointsDifficulte" in out
