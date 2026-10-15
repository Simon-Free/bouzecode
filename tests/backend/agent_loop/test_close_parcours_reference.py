# [desc] Unit tests of proof BY REFERENCE in `parcours_verifies`: the `appel` field names the tool call (alias or id) that proves the journey, and the gate resolves it directly. [/desc]
"""Preuve par RÉFÉRENCE : `appel` = l'alias (`tool_call_alias`) ou l'id de l'appel qui prouve.

Le texte libre de `preuve` restait la seule prise de la porte : 9 refus sur 10 de l'essai du
2026-09-25 venaient d'une correspondance texte ratée. Avec `appel`, la porte résout l'appel
lui-même : il existe, il a réussi, il passe par un navigateur après la dernière retouche
d'interface, et il montre le geste quand l'exigence agit.
"""
from __future__ import annotations

import pytest

from bouzecode.backend.agent import close_parcours as cp


def _session(*appels: tuple[str, dict, str | None]) -> list:
    messages = [{"role": "user", "content": "Ajoute l'édition des énigmes à la page."}]
    for i, (nom, entree, resultat) in enumerate(appels):
        messages.append({"role": "assistant",
                         "tool_calls": [{"id": f"c{i}", "name": nom, "input": entree}]})
        if resultat is not None:
            messages.append({"role": "tool", "tool_call_id": f"c{i}", "content": resultat})
    return messages


PAGE = ("Write", {"file_path": "/home/x/portail/index.html", "content": "<h1/>"}, "Created")
E2E = ("Bash", {"command": "npx playwright test tests/e2e/page.spec.ts",
                "tool_call_alias": "e2e"}, "5 passed")


def _item(appel, exigence: str = "afficher la carte", preuve: str = "voir l'appel") -> dict:
    return {"exigence": exigence, "parcours": "ouvrir la page", "preuve": preuve, "appel": appel}


@pytest.mark.parametrize("reference", ["e2e", "c1", ["e2e"], "  e2e ", '["e2e"]', "e2e, c1"])
def test_un_appel_designe_par_alias_ou_id_prouve_sans_correspondance_texte(reference):
    """La preuve en prose ne correspond à rien : la référence suffit."""
    messages = _session(PAGE, E2E)
    assert cp.manques([_item(reference, preuve="joué, tout est vert")], messages) == []


def test_un_alias_reutilise_designe_le_dernier_appel():
    messages = _session(PAGE,
                        ("Bash", {"command": "npx playwright test", "tool_call_alias": "proof"},
                         "1 failed"),
                        ("Bash", {"command": "npx playwright test", "tool_call_alias": "proof"},
                         "5 passed"))
    assert cp.manques([_item("proof")], messages) == []


def test_une_reference_inconnue_est_refusee_en_la_nommant():
    problemes = cp.manques([_item("smoke42")], _session(PAGE, E2E))
    assert len(problemes) == 1 and "smoke42" in problemes[0]


def test_une_reference_a_un_outil_qui_n_execute_rien_est_refusee():
    ecrire = ("Write", {"file_path": "/home/x/portail/e2e.spec.ts", "content": "x",
                        "tool_call_alias": "w"}, "Created")
    problemes = cp.manques([_item("w")], _session(PAGE, ecrire, E2E))
    assert len(problemes) == 1 and "Write" in problemes[0]


def test_une_reference_a_un_appel_rouge_est_refusee():
    rouge = ("Bash", {"command": "npx playwright test", "tool_call_alias": "e2e"},
             "  ✘  1 [chromium] › page.spec.ts › carte\n  1 failed")
    problemes = cp.manques([_item("e2e")], _session(PAGE, rouge))
    assert len(problemes) == 1 and "échoué" in problemes[0]


def test_une_reference_navigateur_anterieure_a_la_derniere_retouche_est_refusee():
    problemes = cp.manques([_item("e2e")], _session(PAGE, E2E, PAGE))
    assert len(problemes) == 1 and "rejoue" in problemes[0]


def _navigateur(nom: str, alias: str, rendu: str = "ok") -> tuple[str, dict, str]:
    return f"mcp__chrome-devtools__{nom}", {"uid": "1_2", "tool_call_alias": alias}, rendu


def test_une_exigence_qui_agit_se_prouve_par_le_geste_et_le_constat_references():
    messages = _session(PAGE, _navigateur("fill", "f1", "Successfully filled"),
                        _navigateur("take_snapshot", "s1", "uid=1_0 RootWebArea"))
    item = _item(["f1", "s1"], exigence="Modifier l'énoncé de l'énigme")
    assert cp.manques([item], messages) == []


def test_une_exigence_qui_agit_ne_se_prouve_pas_par_un_constat_seul_reference():
    messages = _session(PAGE, _navigateur("take_snapshot", "s1", "uid=1_0 RootWebArea"))
    problemes = cp.manques([_item("s1", exigence="Modifier tous les éléments")], messages)
    assert len(problemes) == 1 and "AGIT" in problemes[0]


def test_sans_reference_le_texte_libre_reste_le_repli():
    item = {"exigence": "afficher la carte", "parcours": "ouvrir la page",
            "preuve": "npx playwright test tests/e2e/page.spec.ts → 5 passed"}
    assert cp.manques([item], _session(PAGE, E2E)) == []


def test_avec_une_reference_la_preuve_textuelle_peut_etre_vide():
    item = {"exigence": "afficher la carte", "parcours": "ouvrir la page", "appel": "e2e"}
    assert cp.manques([item], _session(PAGE, E2E)) == []
