"""Cout d'indexation de findcode : un depot reel indexe en quelques secondes, puis incremental.

Pourquoi le depot lui-meme et non 1300 fichiers fraichement ecrits dans `tmp_path` : profile le
2026-09-29, le corpus synthetique passait 33,5 s des 35,3 s de l'indexation dans `_io.open`, soit
26 ms par PREMIER open d'un fichier tout juste cree sous %TEMP% (filtre antivirus), contre 0,15 ms
pour un fichier deja pose sur disque. Le test mesurait l'antivirus, pas findcode : le parsing des
1300 modules ne pesait que 1,1 s, et le cout par fichier neuf est sur-lineaire (8,6 ms/fichier a
N=200, 17,2 ms/fichier a N=1300) donc impossible a amortir. `src/` du depot offre un corpus REEL
plus riche (pres de 900 fichiers, plus de 8 000 definitions, imports et methodes veritables) pour
environ 3 s. Les seuils, eux, sont inchanges : `cold < 8.0` et `warm < cold / 2`.
"""
import time
from pathlib import Path

from bouzecode.backend.tools.findcode.index import RepoIndex, get_index
from bouzecode.backend.tools.findcode.tools import findcode_tool

# tests/backend/tools/findcode/ -> racine du depot -> son code de production.
SRC = Path(__file__).resolve().parents[4] / "src"

MODULE = '''\
"""Module {i} : gestion des commandes."""
from pkg{prev}.module_{prev} import traiter_{prev}

SEUIL_{i} = {i}


class Service{i}:
    """Service de la commande {i}."""

    def valider(self, commande):
        return commande is not None

    def executer(self, commande):
        if self.valider(commande):
            return traiter_{prev}(commande)
        return None


def traiter_{i}(commande):
    """Traite une commande de niveau {i}."""
    return [commande, SEUIL_{i}]
'''


def test_le_code_de_production_est_indexe_en_quelques_secondes_puis_incremental():
    """Un vrai corpus (le code de bouzecode) indexe a froid, puis un refresh quasi gratuit."""
    # Un index NEUF, pas `get_index` : son cache global `_INDEXES` est partage par toute la
    # session, un autre test aurait deja paye le froid a notre place.
    index = RepoIndex(SRC)

    start = time.perf_counter()
    index.refresh()
    cold = time.perf_counter() - start

    start = time.perf_counter()
    index.refresh()
    warm = time.perf_counter() - start

    # Garde-fous : le budget ci-dessous ne vaut que sur un corpus qui reste consequent.
    assert len(index.files) > 300, f"corpus trop maigre : {len(index.files)} fichiers"
    assert len(index.defs_by_name) > 3000, f"corpus trop maigre : {len(index.defs_by_name)} noms"
    assert "get_index" in index.defs_by_name
    assert cold < 8.0, f"indexation a froid : {cold:.1f} s"
    assert warm < cold / 2, f"appel incremental {warm:.2f} s contre {cold:.2f} s a froid"


def test_l_index_incremental_suit_les_lignes_decalees(tmp_path):
    """Apres edition d'un module, les plages et les appelants sont ceux du fichier a jour."""
    for i in range(3):
        path = tmp_path / f"pkg{i}" / f"module_{i}.py"
        path.parent.mkdir()
        path.write_text(MODULE.format(i=i, prev=max(i - 1, 0)), encoding="utf-8")

    get_index(tmp_path)
    first = findcode_tool({"query": "traiter_1", "path": str(tmp_path)}, {})

    edited = tmp_path / "pkg1" / "module_1.py"
    edited.write_text("# une ligne en tete\n" + edited.read_text(encoding="utf-8"), encoding="utf-8")
    get_index(tmp_path)
    second = findcode_tool({"query": "traiter_1", "path": str(tmp_path)}, {})

    assert "pkg1/module_1.py:L19-21 def traiter_1(commande)" in first
    assert "pkg1/module_1.py:L20-22 def traiter_1(commande)" in second
    assert "called by: pkg2/module_2.py:L15 Service2.executer" in second
