"""Contrat expose a l'assistant : sans outil declare, un canal reste invisible.

`ms_activite.rapport_canaux` ne sert a rien si le modele n'a pas de nom d'outil a
appeler. Ces tests verifient la SURFACE (schema + profil), pas l'implementation Graph.
"""
from __future__ import annotations

from pathlib import Path

import bouzecode
from bouzecode.backend.tools import bureau_tools

PROFIL = (Path(bouzecode.__file__).parent / "backend" / "profiles" / "builtin"
          / "bureau-assistant.yaml")


def _schema(nom: str) -> dict:
    for entree in bureau_tools.BUREAU_TOOL_SCHEMAS:
        if entree.get("name") == nom:
            return entree
    raise AssertionError(f"outil {nom} absent de BUREAU_TOOL_SCHEMAS")


def test_l_outil_canaux_est_expose_avec_une_fenetre_et_un_plafond():
    schema = _schema("Canaux")
    proprietes = schema["input_schema"]["properties"]
    assert "fenetre" in proprietes
    #  Le defaut de conception du 2026-09-09 etait justement l'absence de plafond
    #  reglable : sans `top`, le modele ne peut pas creuser quand on lui dit qu'il
    #  n'a pas tout lu.
    assert "top" in proprietes
    description = schema["description"].lower()
    assert "canal" in description or "canaux" in description
    assert "equipe" in description


def test_la_description_de_teams_dit_qu_elle_ne_couvre_pas_les_canaux():
    """Sinon le modele croit que « Teams » veut dire « tout Teams »."""
    description = _schema("Teams")["description"].lower()
    assert "canaux" in description


def test_le_handler_canaux_existe_et_est_appelable():
    assert callable(getattr(bureau_tools, "canaux", None))


def test_le_profil_de_l_assistant_autorise_l_outil_canaux():
    texte = PROFIL.read_text(encoding="utf-8")
    assert "  - Canaux" in texte
    #  Et il doit DIRE de croiser les trois sources : une demande peut arriver
    #  par mail, par chat ou dans un canal.
    assert "Canaux" in texte.split("## Ce que tu fais")[-1]
