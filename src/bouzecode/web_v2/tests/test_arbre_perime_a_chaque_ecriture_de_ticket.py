# [desc] Toute écriture de ticket (run ajouté, livraison) périme la page d'arbre mémorisée : un enfant fini ne reste pas « préparation… » jusqu'à la fin du TTL. [/desc]
"""Vu par le vérificateur d'invariants (scénario composé `manager-worktree`) : des enfants
restaient affichés « préparation… » plusieurs secondes après leur fin, parce que la page
d'arbre (`fleet_cache`, 10 s) n'était périmée qu'à la NAISSANCE d'un agent. Le passage
« en lancement → lancé → livré » n'est écrit que dans le ticket de l'enfant."""
from __future__ import annotations

import time

import pytest

from bouzecode.web_v2.services.work import fleet_cache, tickets

CLE = ("agent_tree", 0, 12)
SLUG = "demo"


@pytest.fixture(autouse=True)
def cache_neuf():
    fleet_cache.clear()
    yield
    fleet_cache.clear()


def _page_suivie():
    calculs = []

    def calcul():
        calculs.append(1)
        return len(calculs)

    return calculs, calcul


def _attendre_recalcul(calculs, n, limite=5.0):
    fin = time.time() + limite
    while time.time() < fin and len(calculs) < n:
        time.sleep(0.02)
    return len(calculs)


@pytest.mark.parametrize("ecriture", ["add_run", "update_ticket"])
def test_une_ecriture_de_ticket_relance_le_calcul_de_l_arbre(ecriture):
    enfant = tickets.create_ticket(SLUG, "Enfant", "écrire enfant_a.md")
    tickets.set_launching(SLUG, enfant)
    calculs, calcul = _page_suivie()
    assert fleet_cache.cached(CLE, calcul) == 1          # page « enfant en préparation »
    assert fleet_cache.cached(CLE, calcul) == 1          # le TTL tient sans écriture

    if ecriture == "add_run":
        tickets.add_run(SLUG, enfant, "agent-enfant", "work", "")
    else:
        frais = tickets.get_ticket(SLUG, enfant["id"])
        frais["done"] = True
        tickets.update_ticket(SLUG, frais)

    fleet_cache.cached(CLE, calcul)                      # servi tout de suite, recalcul lancé
    assert _attendre_recalcul(calculs, 2) == 2, "l'écriture n'a pas périmé la page d'arbre"
    assert fleet_cache.cached(CLE, calcul) == 2          # le lecteur suivant voit la page fraîche
