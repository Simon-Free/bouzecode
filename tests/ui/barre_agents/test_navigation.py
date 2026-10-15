# [desc] Navigation dans la barre des agents, sans terminal : fleche bas entre dans la liste, haut/bas bornes, Entree ouvre l'agent choisi, Echap revient a main. [/desc]
from __future__ import annotations

from bouzecode.ui.barre_agents.clavier import Navigation

IDS = ["main", "alpha", "alpha.1", "beta"]


def test_fleche_bas_sans_sous_agent_ne_fait_rien():
    nav = Navigation()
    assert nav.entrer_focus(["main"]) is False and nav.focus is False


def test_depuis_main_la_fleche_bas_choisit_le_premier_sous_agent():
    nav = Navigation()
    assert nav.entrer_focus(IDS) is True
    assert nav.selectionne(IDS) == "alpha"


def test_haut_et_bas_restent_dans_la_liste():
    nav = Navigation()
    nav.entrer_focus(IDS)
    for _ in range(10):
        nav.descendre(IDS)
    assert nav.selectionne(IDS) == "beta"
    for _ in range(10):
        nav.monter(IDS)
    assert nav.selectionne(IDS) == "main"


def test_entree_ouvre_l_agent_choisi_puis_echap_revient_a_main():
    nav = Navigation()
    nav.entrer_focus(IDS)
    nav.descendre(IDS)
    assert nav.valider(IDS) == "alpha.1"
    assert (nav.vue, nav.focus) == ("alpha.1", False)
    nav.entrer_focus(IDS)
    assert nav.selectionne(IDS) == "alpha.1"  # la liste repart de l'agent affiche
    assert nav.echapper() == "main"
    assert (nav.vue, nav.focus) == ("main", False)
