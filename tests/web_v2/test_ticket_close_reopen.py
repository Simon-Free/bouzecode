"""Clore / rouvrir un ticket (spec ticketing §5.5, constat C5a), par la machine à états (L2).

L'ancien `POST /done` était une bascule non idempotente qui, sur un ticket au merge bloqué, passait le
worktree en `cleaned` — IRRÉVERSIBLEMENT. Les gestes `close {outcome, reason?}` et `reopen`
sont des transitions (`closed` / `abandoned` / `reopened`) idempotentes, réversibles, qui ne
touchent JAMAIS au worktree. `/done` a été retiré au lot L6.

Test user-centric via le VRAI endpoint Flask, store tickets isolé sous tmp (fixture autouse).
"""
import pytest

from bouzecode.web_v2.services.work import tickets as tickets_svc
from bouzecode.web_v2.services.work.fsm import etats
from bouzecode.web_v2.tests.aides_tickets import projet, run, semer

WORKTREE = {"worktree": "/wt", "branch": "agent/x"}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from bouzecode.web_v2.app import create_app
    projet(tmp_path, monkeypatch, "p")
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def _ticket_merge_bloque(ident: str = "mb000001") -> dict:
    return semer("p", ident, etats.DELIVERED, "merge_bloque", message="arbre principal sale",
                 worktree=dict(WORKTREE), runs=[run("a1", completed=True)])


def test_close_acte_un_merge_bloque_sans_toucher_au_worktree(client):
    ticket = _ticket_merge_bloque()
    assert tickets_svc.derive_status(ticket) == "merge bloqué"

    resp = client.post(f"/api/projects/p/tickets/{ticket['id']}/close",
                       json={"outcome": "accepted", "reason": "mergé à la main"})
    assert resp.status_code == 200
    assert resp.get_json()["done"] is True and resp.get_json()["outcome"] == "accepted"

    fresh = tickets_svc.get_ticket("p", ticket["id"])
    assert fresh["worktree"] == WORKTREE  # JAMAIS retiré ni marqué (C5a)
    assert (fresh["state"], fresh["state_reason"]["message"]) == (etats.CLOSED, "mergé à la main")
    assert tickets_svc.derive_status(fresh) == "terminé"


def test_close_est_idempotent(client):
    ticket = tickets_svc.create_ticket("p", "T", "prompt")
    url = f"/api/projects/p/tickets/{ticket['id']}/close"
    premier = client.post(url, json={"outcome": "abandoned"}).get_json()
    trace = tickets_svc.get_ticket("p", ticket["id"])
    second = client.post(url, json={"outcome": "abandoned"}).get_json()
    assert premier == second
    assert tickets_svc.get_ticket("p", ticket["id"]) == trace  # rien n'a bougé, version comprise


def test_reopen_rend_le_ticket_reintegrable(client):
    ticket = _ticket_merge_bloque()
    client.post(f"/api/projects/p/tickets/{ticket['id']}/close", json={"outcome": "accepted"})

    for _ in range(2):  # idempotent
        resp = client.post(f"/api/projects/p/tickets/{ticket['id']}/reopen")
        assert resp.status_code == 200 and resp.get_json()["done"] is False

    fresh = tickets_svc.get_ticket("p", ticket["id"])
    assert fresh["state"] == etats.DELIVERED and fresh["worktree"] == WORKTREE
    assert tickets_svc.derive_status(fresh) == "à relire"  # de nouveau à décider


def test_close_refuse_une_issue_inconnue(client):
    ticket = tickets_svc.create_ticket("p", "T", "prompt")
    resp = client.post(f"/api/projects/p/tickets/{ticket['id']}/close", json={"outcome": "peut-etre"})
    assert resp.status_code == 400
    assert resp.get_json()["error"]["code"] == "issue_inconnue"
    assert tickets_svc.get_ticket("p", ticket["id"])["state"] == etats.CREATED


def test_close_accepte_un_ticket_jamais_livre_est_refuse(client):
    """Spec §4 : seul un ticket LIVRÉ se clôt « accepté » ; le reste s'abandonne."""
    ticket = tickets_svc.create_ticket("p", "T", "prompt")
    resp = client.post(f"/api/projects/p/tickets/{ticket['id']}/close", json={"outcome": "accepted"})
    assert resp.status_code == 409
    erreur = resp.get_json()["error"]
    assert (erreur["code"], erreur["details"]["state"]) == ("transition_refusee", etats.CREATED)


def test_l_ancienne_bascule_done_n_existe_plus(client):
    ticket = _ticket_merge_bloque()
    assert client.post(f"/api/tickets/p/{ticket['id']}/done").status_code == 404
    assert tickets_svc.get_ticket("p", ticket["id"])["worktree"] == WORKTREE
