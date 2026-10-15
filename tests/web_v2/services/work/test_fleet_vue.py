"""`fleet_vue` : le dernier état MONTRÉ par l'arbre, agent par agent (source de la pastille
« en cours »). Pages construites à la main, instants explicites."""
import pytest

from bouzecode.web_v2.services.work import fleet_cache, fleet_vue


@pytest.fixture(autouse=True)
def registre_vide():
    fleet_cache.clear()
    yield
    fleet_cache.clear()


def _n(ident, etat):
    return {"key": f"agent/{ident}", "agent_id": ident, "etat": etat}


def test_compte_les_agents_montres_au_travail():
    fleet_vue.noter([_n("a", "running"), _n("b", "thinking"), _n("c", "preparing"),
                     _n("d", "awaiting_input"), _n("e", "finished")], 10.0, complet=True)
    assert fleet_vue.au_travail() == 3


def test_une_page_plus_ancienne_ne_fait_pas_reculer_un_agent():
    """Le cache sert du périmé pendant ses recalculs : une page calculée AVANT ce qu'on sait
    déjà d'un agent ne le remet pas dans son ancien état."""
    fleet_vue.noter([_n("a", "finished")], 20.0, complet=False)
    fleet_vue.noter([_n("a", "running")], 10.0, complet=True)
    assert fleet_vue.au_travail() == 0


def test_une_page_complete_retire_les_agents_absents_mais_pas_les_plus_recents():
    fleet_vue.noter([_n("vieux", "running")], 5.0, complet=True)
    fleet_vue.noter([_n("neuf", "running")], 30.0, complet=False)
    fleet_vue.noter([], 20.0, complet=True)
    assert fleet_vue.au_travail() == 1  # « neuf », vu après la page complète, reste


def test_une_page_paginee_ne_retire_que_les_lancements_absents():
    lancement = {"key": "launching/t1", "etat": "preparing"}
    fleet_vue.noter([_n("a", "running"), lancement], 10.0, complet=True)
    fleet_vue.noter([], 11.0, complet=False)
    assert fleet_vue.au_travail() == 1  # l'agent a peut-être glissé hors de la page, pas le lancement


def test_un_changement_de_classe_fait_avancer_la_generation_pas_un_changement_de_phase():
    fleet_vue.noter([_n("a", "running")], 10.0, complet=True)
    avant = fleet_vue.generation()
    assert fleet_vue.noter([_n("a", "thinking")], 11.0, complet=True) is False
    assert fleet_vue.generation() == avant
    assert fleet_vue.noter([_n("a", "awaiting_input")], 12.0, complet=True) is True
    assert fleet_vue.generation() == avant + 1


def test_le_premier_remplissage_ne_perime_rien():
    avant = fleet_vue.generation()
    fleet_vue.noter([_n("a", "running")], 10.0, complet=False)
    assert fleet_vue.generation() == avant
    assert fleet_vue.age_complet() is None


def test_perimer_l_arbre_seul_ne_fait_pas_avancer_la_generation():
    """Le réveil périme l'arbre à chaque tick (tampon de vivacité des tickets) : si cela
    invalidait la boîte, les pastilles la recalculeraient pendant leur requête toutes les 8 s."""
    avant = fleet_vue.generation()
    fleet_cache.expire_all()
    assert fleet_vue.generation() == avant
