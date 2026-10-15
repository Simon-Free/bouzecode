"""Une conversation avec l'assistant du Bureau n'est PAS un travail a faire.

Mesure sur la base reelle (2026-09-09) : `migrate_tickets_into_tasks()` enveloppe CHAQUE
ticket vivant dans une tache v1 dont le titre est `ticket["title"]` — c'est-a-dire le
PROMPT tape par l'humain. Une conversation avec son chef de cabinet etant un ticket comme
un autre, la todolist se remplissait de « Tu peux regarder mes mails/teams de ces 30
derniers jours... », en autant d'exemplaires qu'il y avait eu de conversations (6 tickets
`bureau-assistant` vivants, dont deux crees a la meme seconde par un rejeu de tour).

L'assistant declare desormais ses taches EXPLICITEMENT via l'outil `Taches` : l'
enveloppement automatique n'a plus aucune raison de le doubler.
"""
from bouzecode.web_v2.services.work import task_migration
from bouzecode.web_v2.services.work import tasks as tasks_service
from bouzecode.web_v2.services.work import tickets as tickets_service

SLUG = "bouzecode"
PROMPT = "Tu peux regarder mes mails/teams de ces 30 derniers jours et remplir la todo ?"


def _ticket(titre: str, typologie: str) -> dict:
    """Cree un ticket vivant de la typologie demandee (create_ticket ne la prend pas)."""
    ticket = tickets_service.create_ticket(SLUG, titre, PROMPT)
    ticket["typology"] = typologie
    tickets_service.update_ticket(SLUG, ticket)
    return ticket


def _titres() -> list[str]:
    return [str(t.get("title") or "") for t in tasks_service.list_tasks(include_closed=True)]


def test_une_conversation_avec_l_assistant_ne_fabrique_aucune_tache():
    _ticket(PROMPT, "bureau-assistant")

    assert task_migration.migrate_tickets_into_tasks() == 0
    assert PROMPT not in _titres()


def test_un_ticket_de_code_fabrique_toujours_sa_tache():
    """Non-regression : le filtre ne vise QUE l'assistant du Bureau."""
    _ticket("corriger le calcul de TVA", "coder")

    assert task_migration.migrate_tickets_into_tasks() == 1
    assert "corriger le calcul de TVA" in _titres()


def test_le_filtre_est_idempotent_et_ne_gene_pas_le_reste():
    """Un ticket assistant ecarte ne doit pas empecher les autres d'etre enveloppes."""
    _ticket(PROMPT, "bureau-assistant")
    _ticket("migrer demo_table vers Databricks", "coder")

    assert task_migration.migrate_tickets_into_tasks() == 1
    #  Deuxieme passage : rien de neuf, et surtout pas de doublon.
    assert task_migration.migrate_tickets_into_tasks() == 0
    titres = _titres()
    assert "migrer demo_table vers Databricks" in titres
    assert PROMPT not in titres
