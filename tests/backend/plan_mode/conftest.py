"""Chaque test du mode plan travaille dans son propre dossier.

Le harnais écrit les plans dans `<cwd>/.nano_claude/plans/<session>.md`, avec l'id de
session « default » dans ces tests : sous xdist, tous les processus partageaient la
racine du dépôt et s'écrasaient leurs plans (échecs intermittents, déjà présents avant
l'exclusion git de ce dossier)."""
import pytest


@pytest.fixture(autouse=True)
def _cwd_isole(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
