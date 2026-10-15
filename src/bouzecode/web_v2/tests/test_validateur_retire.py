# [desc] Le validateur de tickets est retiré du backend (D1) : plus de route, runs validate hérités lisibles et clos. [/desc]
"""Spec ticketing §11 D1 = (a) : « le modèle est trop au taquet », on retire le validateur.

Ce que l'utilisateur doit constater : la route `/validate` n'existe plus, un ancien ticket
portant un run `validate` (avec son verdict) s'affiche comme un ticket livré ordinaire, et la
migration de boot clôt ces runs hérités (lot L2 : l'issue est dans `ticket.state`, le watchdog
ne lit plus les runs ; le ticket hérité est SEMÉ dans l'état que lui donne la migration L2).
Vrai store SQLite (isolé par la fixture autouse), vraie app Flask, aucun mock."""
from __future__ import annotations

from bouzecode.web_v2.services.work import migrations, tickets, wake
from bouzecode.web_v2.services.work.fsm import etats
from bouzecode.web_v2.tests.aides_tickets import run, semer

SLUG = "proj"


def _ticket_herite() -> dict:
    """Codeur livré puis run validate (verdict KO) jamais clos : la base d'avant D1, migrée."""
    return semer(SLUG, "ancien01", etats.DELIVERED, title="ancien", runs=[
        run("validateur1", kind="validate", verdict="KO", started_at="2026-07-01T10:05:00"),
        run("codeur1", completed=True, started_at="2026-07-01T10:00:00")])


def test_la_route_validate_n_existe_plus():
    from bouzecode.web_v2.app import create_app
    app = create_app()
    app.config["TESTING"] = True
    regles = {str(r) for r in app.url_map.iter_rules()}
    assert not any(r.endswith("/validate") for r in regles)


def test_un_ancien_verdict_ko_ne_fabrique_plus_de_statut():
    ticket = _ticket_herite()
    assert tickets.derive_status(tickets.get_ticket(SLUG, ticket["id"])) == "à relire"


def test_la_migration_clot_les_runs_validate_herites_une_seule_fois():
    ticket = _ticket_herite()
    assert not next(r for r in ticket["runs"] if r["kind"] == "validate").get("completed")

    assert migrations.migrate_legacy_validate_runs() == 1
    relu = tickets.get_ticket(SLUG, ticket["id"])
    validate = next(r for r in relu["runs"] if r["kind"] == "validate")
    assert validate["completed"] is True
    assert validate["verdict"] == "KO"  # rien n'est effacé : seulement clos
    assert relu["state"] == etats.DELIVERED  # l'état du ticket n'en dépend pas
    assert wake.ticket_needs_watchdog(relu) is False

    assert migrations.migrate_legacy_validate_runs() == 0  # idempotente
