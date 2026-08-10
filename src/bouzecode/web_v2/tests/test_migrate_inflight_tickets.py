# [desc] Migration de boot : les tickets laissés en vol par la chaîne retirée repassent « à relire ». [/desc]
"""Ce que devient un ticket qui attendait une étape désormais supprimée.

Sans cette migration, un ticket resté en `work_done`/`validating` n'aurait plus aucune
transition qui matche : il s'afficherait « en cours » pour toujours. Vrai store de
tickets (isolé sous tmp par la fixture autouse), aucun agent lancé."""
from __future__ import annotations

import pytest

from bouzecode.web_v2.services.work import migrations, tickets


@pytest.fixture()
def projet(monkeypatch):
    """Un unique projet enregistré, comme au démarrage du serveur."""
    monkeypatch.setattr(migrations.projects, "list_projects",
                        lambda: [{"slug": "proj", "name": "Projet", "path": ""}])
    return "proj"


def _ticket_livre(slug: str, **extra) -> dict:
    """Un ticket dont le codeur a livré et dont plus aucun agent ne tourne."""
    ticket = tickets.create_ticket(slug, "Titre", "fais un truc")
    ticket["runs"] = [{"agent_id": "coder-1", "kind": "work", "started_at": "2026-07-01T00:00:00",
                       "verdict": None, "model": ""}]
    ticket.update(extra)
    tickets.update_ticket(slug, ticket)
    return ticket


def test_ticket_en_vol_repasse_a_relire_avec_une_explication(projet):
    """Un ticket laissé en plan par l'ancienne chaîne repasse « à relire » et dit pourquoi."""
    ticket = _ticket_livre(projet, gate_failed_cap=True)

    assert migrations.migrate_inflight_tickets() == 1

    migré = tickets.get_ticket(projet, ticket["id"])
    assert tickets.derive_status(migré) == "à relire"
    assert "chaîne automatique" in migré["comments"][0]["text"]
    assert "gate_failed_cap" not in migré  # drapeau d'un automatisme qui n'existe plus


def test_migration_des_tickets_en_vol_est_idempotente(projet):
    """Rejouer la migration au boot suivant ne re-commente ni ne re-touche rien."""
    ticket = _ticket_livre(projet)

    first = migrations.migrate_inflight_tickets()
    second = migrations.migrate_inflight_tickets()

    assert (first, second) == (1, 0)
    assert len(tickets.get_ticket(projet, ticket["id"])["comments"]) == 1


def test_migration_ne_touche_pas_un_ticket_deja_integre(projet):
    """Un ticket déjà mergé n'est ni recommenté ni ressorti de son état terminal."""
    ticket = _ticket_livre(projet, done=True, worktree={"state": "cleaned"})

    assert migrations.migrate_inflight_tickets() == 0
    assert tickets.get_ticket(projet, ticket["id"])["comments"] == []


def test_migration_ne_touche_pas_un_ticket_jamais_lance(projet):
    """Un ticket créé mais jamais lancé reste « à faire » : il n'a rien à récupérer."""
    ticket = tickets.create_ticket(projet, "Titre", "plus tard")

    assert migrations.migrate_inflight_tickets() == 0
    assert tickets.derive_status(tickets.get_ticket(projet, ticket["id"])) == "à faire"
