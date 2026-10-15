"""La dérivation de l'état d'une tâche : PURE, aucun I/O, chaque ligne de la table §4.1.

Ce test est le contrat de lecture des statuts de tickets. Les libellés testés sont ceux que
`derive_status` rend RÉELLEMENT (relevés sur `_status.py`) : un libellé inventé ici ne prouverait
rien, puisque la dérivation ne verra jamais que ceux-là.
"""
from bouzecode.web_v2.services.work._task_state import derive_task_state


def test_aucun_ticket_donne_a_faire():
    assert derive_task_state([]) == "a_faire"


def test_un_ticket_en_cours_donne_en_cours():
    assert derive_task_state(["en cours"]) == "en_cours"


def test_attend_reponse_est_encore_en_cours():
    assert derive_task_state(["attend réponse"]) == "en_cours"


def test_en_attente_des_enfants_est_en_cours():
    # Libellé rendu par derive_status mais ABSENT de la table de la spec : un manager qui attend
    # ses enfants avance, la tâche n'est ni bloquée ni à relire.
    assert derive_task_state(["en attente des enfants"]) == "en_cours"


def test_chaque_statut_bloquant_bloque_la_tache():
    for status in ("planté", "merge bloqué", "clôture bloquée",
                   "livraison non commitée", "lancement échoué"):
        assert derive_task_state([status]) == "bloquee", status


def test_le_blocage_prime_sur_un_frere_vivant():
    # Sans cette priorité, un ticket planté disparaîtrait derrière un frère « en cours ».
    assert derive_task_state(["en cours", "planté"]) == "bloquee"


def test_a_relire_donne_a_relire():
    assert derive_task_state(["à relire"]) == "a_relire"


def test_un_actif_prime_sur_un_a_relire():
    assert derive_task_state(["à relire", "en cours"]) == "en_cours"


def test_tous_termines_proposent_fait():
    assert derive_task_state(["terminé", "terminé"]) == "fait"


def test_un_seul_termine_parmi_des_actifs_ne_fait_pas_fait():
    assert derive_task_state(["terminé", "en cours"]) == "en_cours"


def test_a_faire_seul_reste_a_faire():
    assert derive_task_state(["à faire"]) == "a_faire"


def test_statuts_vides_sont_ignores_sans_planter():
    assert derive_task_state(["", None]) == "a_faire"
