# [desc] À l'adoption d'un worktree, les extraits gardés sous le dépôt principal sont rebasés sur le worktree si le fichier y est identique ; sinon laissés tels quels. [/desc]
"""Session 9d81964e (2026-10-06) : 8 tours de relecture des fichiers déjà extraits, parce que
les extraits pointaient le dépôt principal et plus le worktree."""
from __future__ import annotations

from bouzecode.backend.context_manager.snippet_rebase import rebaser_extraits
from bouzecode.backend.context_manager.state import METHODOLOGY_NOTE, ContextState
from bouzecode.backend.tools.environment import _rebaser_extraits


def _arbres(tmp_path):
    depot, worktree = tmp_path / "depot", tmp_path / "wt" / "solo"
    for racine in (depot, worktree):
        (racine / "src").mkdir(parents=True)
        (racine / "src" / "client.py").write_text("STAGING_URL = 'x'\n", encoding="utf-8")
        (racine / "src" / "compte.py").write_text("v = 1\n", encoding="utf-8")
    # Modifié dans l'arbre principal, pas dans le worktree (sorti de HEAD) : pas le même texte.
    (depot / "src" / "compte.py").write_text("v = 2  # non commité\n", encoding="utf-8")
    return depot, worktree


def _note(depot, ailleurs):
    return "\n".join([
        "### T3", f"## snippet: {depot / 'src' / 'client.py'} L1-1 — client",
        "STAGING_URL = 'x'", f"## snippet: {depot / 'src' / 'compte.py'} :: v", "v = 2",
        f"## snippet: {ailleurs} L1-2", "autre dépôt"])


def test_seuls_les_extraits_identiques_du_depot_sont_rebases(tmp_path):
    depot, worktree = _arbres(tmp_path)
    ailleurs = tmp_path / "autre.py"
    ailleurs.write_text("a\nb\n", encoding="utf-8")
    etat = ContextState(notes={METHODOLOGY_NOTE: _note(depot, ailleurs)})
    assert rebaser_extraits(etat, str(depot), str(worktree)) == 1
    note = etat.notes[METHODOLOGY_NOTE]
    assert f"## snippet: {worktree / 'src' / 'client.py'} L1-1 — client" in note
    assert f"## snippet: {depot / 'src' / 'compte.py'} :: v" in note  # différent : intact
    assert f"## snippet: {ailleurs} L1-2" in note  # hors du dépôt : intact
    assert "STAGING_URL = 'x'" in note  # le corps de l'extrait n'est pas touché


def test_le_message_d_adoption_dit_de_ne_pas_relire(tmp_path):
    depot, worktree = _arbres(tmp_path)
    config = {"_context_state": ContextState(notes={METHODOLOGY_NOTE: _note(depot, depot)})}
    assert "1 extrait(s)" in _rebaser_extraits(config, str(depot), str(worktree))
    assert _rebaser_extraits({"_context_state": ContextState()}, str(depot), str(worktree)) == ""
