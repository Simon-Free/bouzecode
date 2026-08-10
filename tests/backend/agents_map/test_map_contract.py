# [desc] The permanent drift guard: every generated SYMBOLS.md is re-checked against the live AST. [/desc]
"""Aucune carte du dépôt ne peut annoncer une plage de lignes ou une arête que le code dément."""
from __future__ import annotations

from pathlib import Path

import pytest

from bouzecode.backend.core import context
from bouzecode.backend.tools.agents_map import contract, manifest, regen
from bouzecode.backend.tools.agents_map.nesting import wrong_nesting

REPO = Path(__file__).resolve().parents[3]
MAPS = sorted(REPO.joinpath("src").rglob(manifest.SYMBOLS_DOC))


def _claims_to_be_current(doc: Path) -> bool:
    """A map whose hashes no longer match ALREADY says it is out of date.

    Only a map claiming freshness is worth judging: holding a self-declared stale
    map to the code would just re-report what the manifest already reports, and
    would fail whenever a neighbouring agent edits that folder mid-run.
    """
    recorded, _ = manifest.split_frontmatter(doc.read_text(encoding="utf-8"))
    return not manifest.staleness(
        doc, {"files": manifest.folder_manifest(doc.parent)}, recorded.get("model", ""),
    )


@pytest.mark.skipif(not MAPS, reason="aucune SYMBOLS.md générée dans le dépôt pour l'instant")
@pytest.mark.parametrize("doc", MAPS, ids=lambda p: p.parent.name)
def test_every_map_that_claims_to_be_current_really_is(doc):
    """C'est la vérification que personne n'a faite pendant que loop.py passait de 281 à 676 lignes."""
    if not _claims_to_be_current(doc):
        pytest.skip("carte déjà signalée périmée par son manifeste — elle sera régénérée à la lecture")
    body = doc.read_text(encoding="utf-8")
    folder = doc.parent

    assert contract.wrong_zoom_ranges(body, folder) == []
    assert wrong_nesting(body, folder) == []
    assert contract.cited_identifiers(body) <= regen.legal_identifiers(folder)


@pytest.mark.skipif(not MAPS, reason="aucune SYMBOLS.md générée dans le dépôt pour l'instant")
@pytest.mark.parametrize("doc", MAPS, ids=lambda p: p.parent.name)
def test_no_symbol_map_ever_mentions_a_subfolder(doc):
    """Le découplage est textuel : un SYMBOLS.md ne sait pas qu'il a des voisins."""
    body = doc.read_text(encoding="utf-8")

    assert not contract.has_section(body, "Subfolders")
    assert "/SYMBOLS.md)" not in body


def test_every_call_line_of_a_tree_names_the_file_it_lives_in():
    """L'annotation [fichier] est ce qui transforme un graphe en instrument de navigation."""
    good = "```\nrun()\n ├── helper(x)   [util.py]\n └── other()     [util.py]\n```"
    bad = "```\nrun()\n ├── helper(x)\n └── other()     [util.py]\n```"

    assert contract.annotation_rate(good) == 1.0
    assert contract.annotation_rate(bad) == 0.5


def test_a_control_flow_label_is_not_a_call_and_needs_no_file():
    """Les branches (`├─ [if ...]`) portent la structure, pas une adresse."""
    tree = "```\nrun()\n ├─ [if x]\n │   └── helper()  [util.py]\n```"

    assert contract.annotation_rate(tree) == 1.0


def test_the_navigation_protocol_replaced_the_old_map_walker_and_is_cheaper():
    """Le solde permanent est négatif : on remplace un index par un moins cher."""
    section = context.get_readme_navigation_section()

    assert "AgentsMap()" in section and "SymbolMap(" in section
    assert "## Subfolders" not in section, "l'ancien protocole visait des sections disparues"
    assert len(section) < 400, "le protocole tient en 3-4 lignes, pas en 1 176 caractères"


def test_the_feature_has_exactly_one_global_off_switch(monkeypatch):
    """Une seule échappatoire, et c'est celle qui existait déjà."""
    monkeypatch.setenv("BOUZECODE_README_SYNC", "0")
    assert manifest.feature_enabled() is False
    assert context.get_readme_navigation_section() == ""

    monkeypatch.setenv("BOUZECODE_README_SYNC", "")
    monkeypatch.setenv("BOUZECODE_AGENTS_MAP", "off")
    assert manifest.feature_enabled() is False
