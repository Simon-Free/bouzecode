"""Mémoire courte de la vue du Bureau : rafraîchissement EN FOND des pastilles de navigation.

`/api/nav/counts` est pollé toutes les 15 s par toutes les pages, et la mémoire de 3 s ne
servait jamais d'un poll à l'autre : chaque poll recalculait tout. Passé le TTL, une valeur de
même clé est désormais servie aussitôt et recalculée en fond ; une écriture (clé changée) ou
une valeur trop vieille reste recalculée tout de suite.
"""
import threading
import time

import pytest

from bouzecode.web_v2.services.work import taches_vue


class _Horloge:
    """Horloge monotone pilotée par le test : aucune attente de durée réelle."""

    def __init__(self):
        self.t = 1000.0

    def monotonic(self):
        return self.t

    def avancer(self, secondes):
        self.t += secondes


@pytest.fixture
def horloge(monkeypatch):
    h = _Horloge()
    monkeypatch.setattr(taches_vue, "CACHE_TTL", 3.0)
    monkeypatch.setattr(taches_vue, "time", h)
    taches_vue.invalider()
    yield h
    taches_vue.invalider()


def _compteur():
    appels = []

    def calcul():
        appels.append(1)
        return len(appels)

    return calcul, appels


def _attendre_fin_du_fond(emplacement, delai=5.0):
    """Attente BORNÉE de l'état « plus de recalcul en fond » (horloge réelle)."""
    fin = time.monotonic() + delai
    while emplacement in taches_vue._en_cours and time.monotonic() < fin:
        time.sleep(0.01)
    assert emplacement not in taches_vue._en_cours


def test_valeur_perimee_servie_aussitot_puis_rafraichie_en_fond(horloge):
    calcul, appels = _compteur()
    assert taches_vue.memorise("k", calcul, "essai", en_fond=True) == 1
    horloge.avancer(5)
    assert taches_vue.memorise("k", calcul, "essai", en_fond=True) == 1  # périmée, servie
    _attendre_fin_du_fond("essai")
    assert taches_vue.memorise("k", calcul, "essai", en_fond=True) == 2  # rafraîchie
    assert len(appels) == 2


def test_un_seul_recalcul_en_fond_a_la_fois(horloge):
    lache = threading.Event()
    appels = []

    def lent():
        appels.append(1)
        if len(appels) > 1:
            lache.wait(5)
        return len(appels)

    taches_vue.memorise("k", lent, "essai", en_fond=True)
    horloge.avancer(5)
    for _ in range(5):
        assert taches_vue.memorise("k", lent, "essai", en_fond=True) == 1
    lache.set()
    _attendre_fin_du_fond("essai")
    assert len(appels) == 2


def test_une_ecriture_force_le_recalcul_immediat(horloge):
    calcul, appels = _compteur()
    taches_vue.memorise("generation-1", calcul, "essai", en_fond=True)
    horloge.avancer(5)
    assert taches_vue.memorise("generation-2", calcul, "essai", en_fond=True) == 2


def test_valeur_trop_vieille_recalculee_tout_de_suite(horloge, monkeypatch):
    calcul, appels = _compteur()
    taches_vue.memorise("k", calcul, "essai", en_fond=True)
    horloge.avancer(200)
    assert taches_vue.memorise("k", calcul, "essai", en_fond=True) == 2


def test_sans_en_fond_le_comportement_reste_synchrone(horloge):
    calcul, appels = _compteur()
    taches_vue.memorise("k", calcul, "essai")
    horloge.avancer(5)
    assert taches_vue.memorise("k", calcul, "essai") == 2


def test_pastilles_de_navigation_rafraichies_en_fond(horloge, monkeypatch):
    """`inbox.compteurs` (derrière /api/nav/counts) sert la valeur précédente au poll suivant
    au lieu de tout recalculer pendant la requête — la valeur de LA boîte (emplacement
    « inbox », partagé avec `GET /api/inbox`), pas une copie propre aux pastilles."""
    from bouzecode.web_v2.services.work import fleet, inbox
    comptes = iter(range(1, 100))
    monkeypatch.setattr(inbox, "_construire", lambda: {"compte": next(comptes)})
    monkeypatch.setattr(fleet, "agent_tree", lambda *a, **k: {"nodes": []})
    assert inbox.compteurs()["a_moi"] == 1
    horloge.avancer(5)
    assert inbox.compteurs()["a_moi"] == 1
    _attendre_fin_du_fond("inbox")
    assert inbox.compteurs()["a_moi"] == 2
    assert inbox.construire()["compte"] == 2  # la boîte et la pastille : une seule valeur
