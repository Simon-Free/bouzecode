# [desc] Attente du résultat d'un sous-agent en terminal : réponse FinalAnswer lue, ou fin sans livraison lue dans la fiche de clôture sans attendre le délai maximal. [/desc]
import json
import time

from bouzecode.backend.multi_agent.resultat_terminal import attendre_resultat
from bouzecode.ui.cloture_cli import chemin_fiche


def test_la_reponse_finalanswer_est_lue_et_les_fichiers_supprimes(tmp_path):
    resultat = tmp_path / "agent.result.txt"
    resultat.write_text("fait\n", encoding="utf-8")
    chemin_fiche(resultat).write_text('{"close_reason": "final_answer"}', encoding="utf-8")

    assert attendre_resultat(str(resultat), 5, 0.05) == ("completed", "fait")
    assert not resultat.exists() and not chemin_fiche(resultat).exists()


def test_une_fin_sans_livraison_echoue_des_que_la_fiche_parait(tmp_path):
    resultat = tmp_path / "agent.result.txt"
    chemin_fiche(resultat).write_text(json.dumps(
        {"close_reason": "final_answer_never_called", "close_detail": "", "final_answer": False,
         "code_sortie": 4}), encoding="utf-8")

    debut = time.monotonic()
    statut, texte = attendre_resultat(str(resultat), 30, 0.05)
    assert time.monotonic() - debut < 5  # n'attend pas le délai de 30 s
    assert statut == "failed"
    assert "WITHOUT delivering" in texte and "final_answer_never_called" in texte
    assert "exit code 4" in texte


def test_sans_aucun_fichier_le_delai_expire(tmp_path):
    statut, texte = attendre_resultat(str(tmp_path / "absent.txt"), 0.2, 0.05)
    assert statut == "failed" and "timed out" in texte
