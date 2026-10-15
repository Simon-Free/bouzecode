# [desc] Edit/Write/Read sur un HTML minifié à lignes géantes : écho borné en caractères, changement visible, fichier ordinaire inchangé. [/desc]
"""Un Edit sur un HTML minifié renvoyait 32 k caractères (une <table> par ligne).

Le diff était plafonné en NOMBRE de lignes, jamais en LONGUEUR. Ces tests passent par les
vraies fonctions des outils, sur de vrais fichiers temporaires.
"""
from __future__ import annotations

import difflib
import os
import time

from bouzecode.backend.tools.ops.file_ops import _edit, _read, _write, maybe_truncate_diff
from bouzecode.backend.tools.state import _track_read

PHRASE = "<p>Généré en 233 s (42 566 tokens d'entrée, 9 706 de sortie), accepté du premier coup.</p>"
NOUVELLE = "<p>Généré en 233 s.</p>"


def _cellules(debut: int, nombre: int) -> str:
    return "".join(f"<td>cellule {i} : valeur {i * 7}</td>" for i in range(debut, debut + nombre))


def _html_minifie() -> str:
    """Lignes géantes autour d'une ligne courte, et une phrase au milieu d'une ligne géante."""
    lignes = ["<html><body>", "<h1>Évaluation</h1>"]
    for bloc in range(4):
        lignes.append(f"<table><tr>{_cellules(bloc * 1000, 400)}</tr></table>")
        lignes.append(PHRASE.replace("233", str(233 + bloc)))
    lignes.append(f"<div>{_cellules(9000, 300)}{PHRASE}{_cellules(9500, 300)}</div>")
    lignes.append("</body></html>")
    return "\n".join(lignes) + "\n"


def test_edit_d_une_ligne_courte_entre_des_lignes_geantes_reste_sous_quelques_k(tmp_path):
    fichier = tmp_path / "evaluation.html"
    fichier.write_bytes(_html_minifie().encode("utf-8"))
    assert max(len(l) for l in fichier.read_text(encoding="utf-8").split("\n")) > 10_000

    resultat = _edit(str(fichier), PHRASE.replace("233", "234"), NOUVELLE)

    assert len(resultat) < 6000, len(resultat)
    assert "Zone modifiée : lignes 6–6" in resultat
    assert "-" + PHRASE.replace("233", "234") in resultat
    assert "+" + NOUVELLE in resultat
    assert " car. … " in resultat
    assert NOUVELLE in fichier.read_text(encoding="utf-8")


def test_edit_au_milieu_d_une_ligne_geante_montre_la_fenetre_du_changement(tmp_path):
    fichier = tmp_path / "evaluation.html"
    fichier.write_bytes(_html_minifie().encode("utf-8"))
    ligne_div = fichier.read_text(encoding="utf-8").split("\n")[10]

    resultat = _edit(str(fichier), "<div>" + _cellules(9000, 300) + PHRASE, "<div>" + _cellules(9000, 300) + NOUVELLE)

    assert len(resultat) < 6000, len(resultat)
    assert "Zone modifiée : lignes 11–11" in resultat
    retiree = next(l for l in resultat.split("\n") if l.startswith("-[car."))
    ajoutee = next(l for l in resultat.split("\n") if l.startswith("+[car."))
    assert "accepté du premier coup" in retiree and "accepté" not in ajoutee
    assert "233 s.</p>" in ajoutee
    debut = ligne_div.index(PHRASE) + len("<p>Généré en 233 s") - 100 + 1
    assert f"[car. {debut}–" in retiree and f"sur {len(ligne_div)}]" in retiree


def test_un_fichier_ordinaire_produit_le_meme_diff_qu_avant(tmp_path):
    ancien = "".join(f"ligne {i} = {i * 3}\n" for i in range(30))
    nouveau = ancien.replace("ligne 14 = 42", "ligne 14 = 43")
    diff = "".join(difflib.unified_diff(ancien.splitlines(True), nouveau.splitlines(True),
                                        fromfile="a/x.py", tofile="b/x.py", n=3))
    assert maybe_truncate_diff(diff, max_lines=40) == diff

    fichier = tmp_path / "x.py"
    fichier.write_bytes(ancien.encode("utf-8"))
    resultat = _edit(str(fichier), "ligne 14 = 42", "ligne 14 = 43")
    assert diff in resultat
    assert "car. …" not in resultat


def test_write_d_un_fichier_a_lignes_geantes_rend_un_apercu_borne(tmp_path):
    contenu = _html_minifie()
    fichier = tmp_path / "nouveau.html"

    cree = _write(str(fichier), contenu)
    assert len(cree) < 4000, len(cree)
    assert fichier.read_text(encoding="utf-8") == contenu

    mis_a_jour = _write(str(fichier), contenu.replace(PHRASE.replace("233", "235"), NOUVELLE))
    assert len(mis_a_jour) < 6000, len(mis_a_jour)
    assert "+" + NOUVELLE in mis_a_jour


def test_avertissement_fichier_modifie_hors_agent_est_borne(tmp_path):
    fichier = tmp_path / "evaluation.html"
    contenu = _html_minifie()
    fichier.write_bytes(contenu.encode("utf-8"))
    _track_read(str(fichier), content=contenu)
    fichier.write_bytes((contenu.replace("cellule 1200 ", "cellule MODIFIEE ")).encode("utf-8"))
    os.utime(fichier, (time.time() + 5, time.time() + 5))

    resultat = _edit(str(fichier), PHRASE.replace("233", "236"), NOUVELLE)

    assert resultat.startswith("[Warning] File was modified on disk")
    assert "cellule MODIFIEE" in resultat
    assert len(resultat) < 10_000, len(resultat)


def test_plan_d_un_gros_fichier_minifie_n_affiche_pas_ses_lignes_entieres(tmp_path):
    fichier = tmp_path / "gros.html"
    fichier.write_bytes((_html_minifie() * 40).encode("utf-8"))

    plan = _read(str(fichier))

    assert "trop long pour un Read" in plan
    assert len(plan) < 40_000, len(plan)
    assert " car. … " in plan
