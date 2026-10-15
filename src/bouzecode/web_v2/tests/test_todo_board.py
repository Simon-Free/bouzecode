"""La vue TO-DO regroupe les tâches restantes DÉCLARÉES par macro-tâche.

Aucun mock : la source de lecture est un contrat duck-typé, on en fournit une
implémentation de test qui rend exactement ce que le disque rendrait.
"""
from datetime import datetime, timedelta

from bouzecode.web_v2.services.work import todo_board

NOW = datetime(2026, 8, 27, 12, 0, 0)


def _ticket(tid, agent, titre, jours=0, done=True):
    #  Forme RÉELLE d'un ticket du parc : la clôture se lit dans `state` (lot L2), et
    #  l'agent dans `runs[0].agent_id` (le run le plus récent est en tête).
    return {
        "id": tid, "slug": "proj", "title": titre,
        "state": "closed" if done else "running",
        "runs": [{"agent_id": agent}],
        "created_at": (NOW - timedelta(days=jours)).isoformat(),
    }


class Source:
    def __init__(self, tickets, taches=None, recaps=None, tests=()):
        self._tickets = tickets
        self._taches = taches or {}
        self._recaps = recaps or {}
        self._tests = set(tests)

    def tickets(self):
        return list(self._tickets)

    def taches(self, agent_id):
        return self._taches.get(agent_id)

    def recap(self, agent_id):
        return self._recaps.get(agent_id)

    def is_test(self, agent_id):
        return agent_id in self._tests


LONG = ("Rebrancher le poller sur l'état running du ticket, puis vérifier que la "
        "reprise après un crash du subprocess ne réordonne pas les messages déjà "
        "affichés dans la conversation ouverte par l'utilisateur.")


def test_puces_regroupees_sous_la_macro_declaree():
    source = Source(
        [_ticket("t1", "a1", "Mission A"), _ticket("t2", "a2", "Mission B")],
        taches={
            "a1": {"taches_declarees": True, "taches_restantes": [
                {"macro": "Poller", "texte": LONG},
                {"macro": "Poller", "texte": "Ajouter le test de reprise"},
            ]},
            "a2": {"taches_declarees": True, "taches_restantes": [
                {"macro": "Coûts", "texte": "Agréger par jour"},
            ]},
        },
    )
    vue = todo_board.collect(source, now=NOW, fenetre="7j")
    noms = [groupe["macro"] for groupe in vue["macros"]]
    assert noms == ["Coûts", "Poller"]
    poller = [g for g in vue["macros"] if g["macro"] == "Poller"][0]
    assert len(poller["puces"]) == 2
    assert poller["deduit"] is False
    assert vue["stats"]["puces"] == 3
    assert vue["stats"]["non_declare"] == 0


def test_le_texte_entier_est_conserve_sans_troncature():
    source = Source([_ticket("t1", "a1", "Mission A")], taches={
        "a1": {"taches_declarees": True,
               "taches_restantes": [{"macro": "Poller", "texte": LONG}]},
    })
    vue = todo_board.collect(source, now=NOW)
    assert vue["macros"][0]["puces"][0]["texte"] == LONG
    assert "…" not in vue["macros"][0]["puces"][0]["texte"]


def test_liste_vide_declaree_ne_produit_aucune_puce():
    source = Source([_ticket("t1", "a1", "Mission A")], taches={
        "a1": {"taches_declarees": True, "taches_restantes": []},
    })
    vue = todo_board.collect(source, now=NOW)
    assert vue["macros"] == []
    assert vue["stats"]["puces"] == 0
    assert vue["stats"]["non_declare"] == 0


def test_cloture_ancienne_est_affichee_non_declaree():
    source = Source([_ticket("t1", "a1", "Mission ancienne")])
    vue = todo_board.collect(source, now=NOW)
    puce = vue["macros"][0]["puces"][0]
    assert puce["declare"] is False
    assert puce["texte"] == todo_board.TEXTE_NON_DECLARE
    assert vue["macros"][0]["deduit"] is True
    #  Le brief refuse une section par ticket : tout ce qui n'est pas rattaché tombe
    #  dans UNE section déduite, le titre du ticket restant lisible sur la puce.
    assert vue["macros"][0]["macro"] == todo_board.MACRO_NON_RATTACHEE
    assert puce["title"] == "Mission ancienne"
    assert vue["stats"]["non_declare"] == 1


def test_points_ouverts_anciens_migrent_en_taches_a_decider():
    source = Source([_ticket("t1", "a1", "Mission ancienne")], recaps={
        "a1": {"points_ouverts": [{"texte": "Garder ou non le fallback ?",
                                   "options": [{"key": "oui", "label": "Garder"}]}]},
    })
    vue = todo_board.collect(source, now=NOW)
    assert len(vue["a_decider"]) == 1
    assert vue["a_decider"][0]["texte"] == "Garder ou non le fallback ?"
    assert vue["a_decider"][0]["declare"] is False
    assert vue["macros"] == []


def test_decision_declaree_va_dans_a_decider():
    source = Source([_ticket("t1", "a1", "Mission A")], taches={
        "a1": {"taches_declarees": True, "taches_restantes": [
            {"macro": "Poller", "texte": "Faire X"},
            {"macro": "Poller", "texte": "Règle métier à confirmer", "decision": True},
        ]},
    })
    vue = todo_board.collect(source, now=NOW)
    assert [p["texte"] for p in vue["a_decider"]] == ["Règle métier à confirmer"]
    assert len(vue["macros"][0]["puces"]) == 1
    assert vue["stats"]["a_decider"] == 1


def test_conversations_de_test_exclues():
    source = Source(
        [_ticket("t1", "a1", "PING/PONG"), _ticket("t2", "a2", "Mission A")],
        taches={"a2": {"taches_declarees": True,
                       "taches_restantes": [{"macro": "M", "texte": "Faire X"}]}},
        tests=["a1"],
    )
    vue = todo_board.collect(source, now=NOW)
    assert vue["stats"]["tickets"] == 1
    assert [g["macro"] for g in vue["macros"]] == ["M"]


def test_ticket_non_termine_et_hors_fenetre_ignores():
    source = Source([
        _ticket("t1", "a1", "En cours", done=False),
        _ticket("t2", "a2", "Trop vieux", jours=10),
    ], taches={
        "a1": {"taches_declarees": True, "taches_restantes": [{"macro": "M", "texte": "X"}]},
        "a2": {"taches_declarees": True, "taches_restantes": [{"macro": "M", "texte": "Y"}]},
    })
    vue = todo_board.collect(source, now=NOW, fenetre="2j")
    assert vue["stats"]["tickets"] == 0
    assert vue["macros"] == []
