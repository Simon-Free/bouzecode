"""L'« intent » d'une tâche migrée doit venir du PROMPT du ticket racine.

La migration de boot enveloppe chaque ticket racine dans une tâche ; jusqu'ici cette tâche
naissait avec une `intent` vide et un titre brut : sur le board, une sous-tâche par ticket,
sans contexte rédigé. Ces tests exigent que :
- la migration renseigne l'intent depuis le prompt du ticket racine ;
- la réconciliation continue remplisse les tâches anciennes restées sans intent (backfill) ;
- un ticket sans prompt ne produise PAS d'intent inventée.
"""

from bouzecode.web_v2.services.work import task_migration, tickets
from bouzecode.web_v2.services.work import tasks as tasks_service


def _ticket(slug: str, title: str, prompt: str) -> dict:
    """Crée un ticket vivant (sans run terminé) avec LE prompt voulu."""
    return tickets.create_ticket(slug, title, prompt)


def test_la_migration_renseigne_lintent_depuis_le_prompt_du_ticket_racine():
    _ticket("proj", "crash poller",
            "Corriger le crash du poller : le watchdog doit survivre aux redémarrages.")
    task_migration.migrate_tickets_into_tasks()
    tasks_lues = tasks_service.list_tasks()
    assert len(tasks_lues) == 1
    assert "watchdog" in tasks_lues[0]["intent"]
    # La migration rejouée ne doit rien réécrire ni dupliquer.
    task_migration.migrate_tickets_into_tasks()
    assert len(tasks_service.list_tasks()) == 1


def test_la_reconciliation_remplit_les_taches_anciennes_sans_intent():
    ticket = _ticket("proj", "specs bureau",
                     "Enrichir les specs existantes du Bureau regroupées par thème.")
    task = tasks_service.create_task("sous-tâche brute de migration")  # intent vide
    tasks_service.link_ticket(task["id"], "proj", ticket["id"])
    result = task_migration.reconcile_tasks_with_tickets()
    lu = tasks_service.get_task(task["id"])
    assert "specs" in lu["intent"], result
    assert not lu.get("outcome")  # '' = pas close


def test_un_ticket_sans_prompt_ne_genere_pas_dintent():
    _ticket("proj", "sans prompt", "")
    task_migration.migrate_tickets_into_tasks()
    tasks_lues = tasks_service.list_tasks()
    assert len(tasks_lues) == 1
    assert tasks_lues[0]["intent"] == ""
