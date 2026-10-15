"""Un manager (NON_CODING_TYPOLOGIES) qui rend une FinalAnswer à chaque tour clôt son
process GRACIEUSEMENT (close_reason=final_answer). Sa fin de run ne doit PAS le faire passer
« livré » tant qu'un enfant est encore ACTIF (en préparation ou en cours) — sinon le manager est
figé « Terminé » et n'est plus jamais réveillé pour superviser/relancer l'enfant (orchestration
gelée). Régression : symptôme 2 du ticket 3a10b789e662.

Lot L2 : la fin de run est `constats.fin_de_run` (hook ou watchdog) ; un parent dont un enfant
est actif reste `running` avec un run `awaiting_children`. Vrai store, aucun mock."""
from bouzecode.web_v2.services.work import constats, tickets
from bouzecode.web_v2.services.work.fsm import cycle_des_runs, etats
from bouzecode.web_v2.tests.aides_tickets import amener, en_cours

SLUG = "proj"


def _manager() -> dict:
    return en_cours(SLUG, "mgr-1", "pilote", typology="manager")


def _enfant(agent_id: str | None = None) -> dict:
    """Un enfant du manager : lancé (préparation) ; avec `agent_id`, son run tourne."""
    if agent_id:
        return en_cours(SLUG, agent_id, "enfant", parent="mgr-1")
    enfant = tickets.create_ticket(SLUG, "enfant", "faire")
    tickets.poser(SLUG, enfant, parent="mgr-1")
    tickets.set_launching(SLUG, enfant)
    return enfant


def _fin_du_tour(manager: dict) -> dict:
    constats.fin_de_run(SLUG, manager["id"], "mgr-1", "final_answer", final_answer=True)
    return tickets.get_ticket(SLUG, manager["id"])


def test_manager_not_completed_while_child_pending_launch():
    manager = _manager()
    _enfant()  # fraîchement (re)dispatché : en préparation, pas encore de run

    frais = _fin_du_tour(manager)

    assert frais["state"] == etats.RUNNING, "le manager reste RÉVEILLABLE tant qu'un enfant démarre"
    assert cycle_des_runs.run_courant(frais)["state"] == cycle_des_runs.RUN_AWAITING_CHILDREN
    assert not frais["runs"][0].get("completed")


def test_manager_not_completed_while_child_running():
    manager = _manager()
    _enfant("kid-1")

    frais = _fin_du_tour(manager)

    assert frais["state"] == etats.RUNNING, "le manager ne doit PAS livrer tant qu'un enfant tourne"
    assert tickets.derive_status(frais) == "en attente des enfants"


def test_manager_completed_when_all_children_terminal():
    manager = _manager()
    enfant = _enfant("kid-1")
    amener(SLUG, enfant, etats.RUN_ENDED, delivered=True, close_reason="final_answer")

    frais = _fin_du_tour(manager)

    assert frais["state"] == etats.DELIVERED, "manager finalisable quand tous les enfants ont fini"
    assert frais["runs"][0]["completed"] is True


def test_manager_completed_when_no_children():
    frais = _fin_du_tour(_manager())

    assert frais["state"] == etats.DELIVERED, "manager sans enfant doit être finalisable"
