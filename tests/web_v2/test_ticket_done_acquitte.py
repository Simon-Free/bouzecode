"""Fix 2 — POST /done acquitte un merge bloqué (worktree needs_attention).

Test user-centric via le VRAI endpoint Flask (client de test), store tickets sur un
dossier temp réel (pas de mock du service). Sans ce fix, marquer done à la main un ticket
'merge bloqué' le laisserait 'merge bloqué' à vie (Fix1 prime sur done) : on vérifie que
le done manuel pose l'acquittement meta state=cleaned + resolved_by=manual-done.
"""
import pytest

from bouzecode.web_v2.services.work import tickets as tickets_svc


@pytest.fixture()
def client():
    """Le store est isolé sous tmp par la fixture autouse `_isolate_production_state`."""
    from bouzecode.web_v2.app import create_app
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_done_manuel_acquitte_le_merge_bloque(client):
    """POST /done sur un ticket needs_attention : done True + acquittement cleaned."""
    ticket = tickets_svc.create_ticket("p", "T", "prompt")
    ticket["worktree"] = {"state": "needs_attention"}
    tickets_svc.update_ticket("p", ticket)

    resp = client.post(f"/api/tickets/p/{ticket['id']}/done")
    assert resp.status_code == 200
    assert resp.get_json()["done"] is True

    fresh = tickets_svc.get_ticket("p", ticket["id"])
    assert fresh["done"] is True
    assert fresh["worktree"]["state"] == "cleaned"
    assert fresh["worktree"]["resolved_by"] == "manual-done"
    # Le board affiche bien 'terminé' (plus 'merge bloqué') une fois acquitté.
    assert tickets_svc.derive_status(fresh) == "terminé"


def test_done_manuel_sans_needs_attention_ne_touche_pas_le_worktree(client):
    """Un ticket ordinaire marqué done ne se voit pas inventer un acquittement."""
    ticket = tickets_svc.create_ticket("p", "T2", "prompt")

    resp = client.post(f"/api/tickets/p/{ticket['id']}/done")
    assert resp.status_code == 200

    fresh = tickets_svc.get_ticket("p", ticket["id"])
    assert fresh["done"] is True
    assert fresh.get("worktree", {}).get("resolved_by") is None
