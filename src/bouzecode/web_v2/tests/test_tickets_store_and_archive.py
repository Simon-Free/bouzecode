"""Store de tickets (backend SQLite WAL) : archivage manuel réversible.

Le store est désormais une base SQLite WAL (atomicité/durabilité/concurrence multi-process
natives) — les rustines du rewrite JSON monolithique (auto-heal `.bak`, quarantaine « corrupt »,
sweep des `.tmp` orphelins) n'ont plus d'objet et ont été retirées. Archiver un ticket reste
MANUEL, réversible, et ne supprime jamais rien du store. Aucun mock : vraie DB dans un
TICKETS_DIR temporaire (monkeypatch).
"""
import pytest


@pytest.fixture()
def T():
    """La façade tickets. Le store est isolé sous tmp par la fixture autouse
    `_isolate_production_state` — c'est `_persistence.TICKETS_DIR` qu'elle redirige, pas le
    ré-export `tickets.TICKETS_DIR` que ce fixture posait en vain."""
    from bouzecode.web_v2.services.work import tickets as mod
    return mod


# ── Archivage manuel réversible ───────────────────────────────────────────────

def test_archive_hides_from_board_but_keeps_in_store(T):
    a = T.create_ticket("proj", "A", "p")
    T.create_ticket("proj", "B", "p")
    assert T.archive_ticket("proj", a["id"]) is not None
    active = [t["id"] for t in T.list_tickets("proj")]
    assert a["id"] not in active and len(active) == 1          # masqué du board
    allt = [t["id"] for t in T.list_tickets("proj", include_archived=True)]
    assert a["id"] in allt                                      # toujours dans le store
    assert T.get_ticket("proj", a["id"])["archived"] is True    # jamais supprimé


def test_unarchive_restores_to_board(T):
    a = T.create_ticket("proj", "A", "p")
    T.archive_ticket("proj", a["id"])
    assert T.unarchive_ticket("proj", a["id"]) is not None
    assert a["id"] in [t["id"] for t in T.list_tickets("proj")]
    assert "archived" not in T.get_ticket("proj", a["id"])


def test_archive_unknown_ticket_returns_none(T):
    assert T.archive_ticket("proj", "inconnu") is None
    assert T.unarchive_ticket("proj", "inconnu") is None


def test_archive_route_flask(T):
    from bouzecode.web_v2.app import create_app
    a = T.create_ticket("proj", "A", "p")
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        r = c.post(f"/api/tickets/proj/{a['id']}/archive")
        assert r.status_code == 200 and r.get_json()["archived"] is True
        assert T.get_ticket("proj", a["id"])["archived"] is True
        r2 = c.post(f"/api/tickets/proj/{a['id']}/unarchive")
        assert r2.status_code == 200 and r2.get_json()["archived"] is False
        r3 = c.post("/api/tickets/proj/nope/archive")
        assert r3.status_code == 404
