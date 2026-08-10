# [desc] Le journal de raisonnement garde UN tour par entrée, au lieu de réécrire tout l'historique. [/desc]
"""Chaque entrée de `thinking_log` ne contient QUE le raisonnement de son tour.

LE DÉFAUT (2026-07-30) : l'accumulateur de raisonnement, créé une fois par message utilisateur,
n'était jamais vidé, alors qu'une entrée est écrite à chaque fin de tour. Chaque entrée
réécrivait donc les précédentes → croissance en O(tours²). Mesuré sur une vraie session de
270 tours : 259 entrées sur 259 étaient un préfixe strict de la suivante, 649 Ko de texte
unique stockés sur 109 Mo (facteur 171). Première cause des JSON de session à 113 Mo.

POURQUOI UN TEST DIRECT et non une conversation : `tests/e2e_harness.py` importe
`backend.agent.loop.run` et ne traverse JAMAIS `ui/repl.py`, où ce journal est écrit. Aucune
conversation scriptée ne peut l'atteindre — c'est précisément pour ça que le bug a survécu.
`flush_thinking` est le geste extrait de la boucle pour le rendre observable.
"""
from bouzecode.ui.repl import flush_thinking


def test_deux_tours_donnent_deux_entrees_qui_ne_se_recouvrent_pas():
    """Le raisonnement du tour 2 ne réécrit pas celui du tour 1 (avant : il le contenait)."""
    accumulateur, journal = [], []

    accumulateur.append("PREMIER raisonnement.")
    flush_thinking(accumulateur, turn=1, thinking_log=journal)
    accumulateur.append("SECOND raisonnement.")
    flush_thinking(accumulateur, turn=2, thinking_log=journal)

    assert [e["turn"] for e in journal] == [1, 2]
    assert journal[0]["text"] == "PREMIER raisonnement."
    assert journal[1]["text"] == "SECOND raisonnement."
    assert "PREMIER" not in journal[1]["text"]


def test_le_journal_pese_la_somme_des_tours_et_non_leur_cumul():
    """Sur 10 tours, le journal pèse 10 raisonnements — pas 55 (1+2+…+10), la loi du bug."""
    accumulateur, journal = [], []
    raisonnement = "x" * 100

    for tour in range(1, 11):
        accumulateur.append(raisonnement)
        flush_thinking(accumulateur, turn=tour, thinking_log=journal)

    assert sum(len(e["text"]) for e in journal) == 10 * len(raisonnement)


def test_un_tour_sans_raisonnement_n_ecrit_aucune_entree():
    """Rien à consigner ne crée pas d'entrée vide, et l'accumulateur reste utilisable."""
    accumulateur, journal = [], []

    assert flush_thinking(accumulateur, turn=1, thinking_log=journal) == ""
    assert journal == []


def test_l_accumulateur_est_vide_apres_ecriture():
    """C'est LA garantie : sans ce vidage, le tour suivant réécrit tout l'historique."""
    accumulateur, journal = ["du raisonnement"], []

    flush_thinking(accumulateur, turn=1, thinking_log=journal)

    assert accumulateur == []
