# [desc] Un manager dont un enfant a planté sans rien livrer ne peut pas être enregistré « terminé ». [/desc]
"""Le garde-fou de clôture d'un manager (cas réel 642e1a3f / enfant c08d9758).

Histoire : un manager dispatche des enfants, rend son tour (« VERDICT: OK », il est `delivered`)
et le watchdog veut le clore. Tant qu'un enfant a planté sans écrire une ligne, la clôture est
REFUSÉE, dite à l'écran (`delivered{cloture_bloquee}`, « Bloqué ») et tracée sur le ticket ;
dès que l'enfant livre (ou qu'un humain tranche), elle repart. Store SQLite réel, aucun mock.
"""
from __future__ import annotations

import pytest

from bouzecode.web_v2.services.work import closure_guard, constats, ticket_fsm, wake
from bouzecode.web_v2.services.work import tickets as tickets_svc
from bouzecode.web_v2.services.work.fsm import etats
from bouzecode.web_v2.tests.aides_tickets import en_cours, livre, projet, run, semer

SLUG = "projet-du-manager"
MANAGER_AGENT = "mgr-1"


class _ParentAgent:
    """Ce que `wake` connaît du manager : son ticket. (Le vrai `runner.Agent` en dit plus.)"""

    def __init__(self, slug: str, ticket_id: str):
        self.ticket_slug, self.ticket_id = slug, ticket_id


@pytest.fixture()
def manager() -> dict:
    return livre(SLUG, MANAGER_AGENT, typology="manager")


def _child(title: str, agent_id: str, *, delivered: bool, crashed: bool = False) -> dict:
    ticket = en_cours(SLUG, agent_id, titre=title, parent=MANAGER_AGENT)
    if delivered:
        constats.fin_de_run(SLUG, ticket["id"], agent_id, "final_answer")
    elif crashed:
        ticket_fsm.appliquer(SLUG, ticket["id"], etats.CRASHED, code="crashed")
    return tickets_svc.get_ticket(SLUG, ticket["id"])


def _finalize(manager: dict, children: list[dict]) -> bool:
    return wake._finalize_noncoding_parent(_ParentAgent(SLUG, manager["id"]), children)


def _reload(ticket: dict) -> dict:
    return tickets_svc.get_ticket(SLUG, ticket["id"])


# ── (a) l'enfant planté sans livraison gèle la clôture, et ça se voit ────────────────────

def test_a_manager_is_not_closed_while_a_child_crashed_without_delivering(manager):
    crashed = _child("stockage azure", "coder-mort", delivered=False, crashed=True)
    children = [_child("inventaire", "coder-1", delivered=True), crashed]
    assert _finalize(manager, children) is False
    stored = _reload(manager)
    assert stored["state"] == etats.DELIVERED, "le manager a été clos malgré un enfant planté"
    assert stored["state_reason"]["code"] == closure_guard.CLOSURE_BLOCKED_CODE
    assert tickets_svc.derive_status(stored) == "clôture bloquée"


def test_a_the_refusal_names_the_guilty_child_and_the_way_out(manager):
    crashed = _child("stockage azure", "coder-mort", delivered=False, crashed=True)
    _finalize(manager, [crashed])
    trace = _reload(manager)["comments"][-1]["text"]
    assert crashed["id"] in trace
    assert "Clôture BLOQUÉE" in trace
    assert "aucune livraison" in trace
    assert f"/api/projects/{SLUG}/tickets/{manager['id']}/close" in trace


def test_a_a_repeated_watchdog_tick_does_not_repeat_the_trace(manager):
    crashed = _child("stockage azure", "coder-mort", delivered=False, crashed=True)
    for _ in range(4):
        _finalize(manager, [crashed])
    assert len(_reload(manager)["comments"]) == 1


def test_a_a_child_dead_before_it_is_constated_also_blocks(manager):
    """Même avant que le watchdog n'ait constaté sa mort (debounce), un enfant qui n'a rien
    livré bloque : sinon la fausse clôture passait simplement deux ticks plus tôt."""
    silent = _child("stockage azure", "coder-muet", delivered=False)
    assert _finalize(manager, [silent]) is False
    assert tickets_svc.derive_status(_reload(manager)) == "clôture bloquée"


# ── (b) la clôture légitime n'est pas cassée ─────────────────────────────────────────────

def test_b_a_manager_whose_children_all_delivered_is_closed_normally(manager):
    children = [_child("inventaire", "coder-1", delivered=True),
                _child("gateway", "coder-2", delivered=True)]
    assert _finalize(manager, children) is True
    stored = _reload(manager)
    assert stored["state"] == etats.CLOSED
    assert tickets_svc.derive_status(stored) == "terminé"


def test_b_a_child_that_delivered_after_crashing_stops_blocking(manager):
    """L'enfant relancé qui livre enfin lève le blocage — et le statut cesse de le dire."""
    child = _child("stockage azure", "coder-mort", delivered=False, crashed=True)
    assert _finalize(manager, [child]) is False
    tickets_svc.set_launching(SLUG, child)
    tickets_svc.add_run(SLUG, child, "coder-repris", "work", "opus")
    constats.fin_de_run(SLUG, child["id"], "coder-repris", "final_answer")
    assert _finalize(manager, [_reload(child)]) is True
    stored = _reload(manager)
    assert stored["state"] == etats.CLOSED
    assert stored["state_reason"]["code"] == "routage_termine"


# ── (c) un enfant dont le sort est tranché ne gèle pas son parent ───────────────────────

def _excuse_archive(child: dict) -> dict:
    tickets_svc.archive_ticket(SLUG, child["id"])
    return _reload(child)


def _excuse_abandon(child: dict) -> dict:
    return ticket_fsm.appliquer(SLUG, child["id"], etats.ABANDON)


def _excuse_fauche(child: dict) -> dict:
    return semer(SLUG, child["id"], etats.CLOSED, "integre", runs=[run("coder-mort")],
                 parent=MANAGER_AGENT, worktree={"worktree": "/wt", "retire_at": "2026-10-01"})


@pytest.mark.parametrize("excuse", [_excuse_archive, _excuse_abandon, _excuse_fauche])
def test_c_an_abandoned_child_does_not_freeze_its_parent(manager, excuse):
    """Un enfant archivé, abandonné ou mergé-fauché ne bloque pas son manager, même planté."""
    child = excuse(_child("stockage azure", "coder-mort", delivered=False, crashed=True))
    assert _finalize(manager, [child]) is True
    assert _reload(manager)["state"] == etats.CLOSED


def test_c_a_child_that_never_started_does_not_block(manager):
    never_launched = tickets_svc.create_ticket(SLUG, "jamais lancé", "…")
    assert _finalize(manager, [never_launched]) is True


# ── (d) la porte de sortie humaine ───────────────────────────────────────────────────────

@pytest.fixture()
def client(tmp_path, monkeypatch):
    from bouzecode.web_v2.app import create_app
    projet(tmp_path, monkeypatch, SLUG)
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as test_client:
        yield test_client


def test_d_a_human_can_force_the_closure_and_it_is_traced(manager, client):
    crashed = _child("stockage azure", "coder-mort", delivered=False, crashed=True)
    _finalize(manager, [crashed])
    resp = client.post(f"/api/projects/{SLUG}/tickets/{manager['id']}/close", json={"outcome": "accepted"})
    assert resp.status_code == 200
    assert resp.get_json()["closure_forced"] == crashed["id"]
    stored = _reload(manager)
    assert (stored["state"], stored["state_reason"]["code"]) == (etats.CLOSED, "cloture_forcee")
    assert tickets_svc.derive_status(stored) == "terminé"
    assert "Clôture FORCÉE" in stored["comments"][-1]["text"]
    assert crashed["id"] in stored["comments"][-1]["text"]


def test_d_a_forced_closure_is_never_re_blocked_by_the_watchdog(manager, client):
    crashed = _child("stockage azure", "coder-mort", delivered=False, crashed=True)
    _finalize(manager, [crashed])
    client.post(f"/api/projects/{SLUG}/tickets/{manager['id']}/close", json={"outcome": "accepted"})
    assert closure_guard.refuse_closure(SLUG, _reload(manager), [crashed]) == []
    assert _reload(manager)["state_reason"]["code"] == "cloture_forcee"


def test_d_closing_an_unblocked_ticket_forces_nothing(manager, client):
    resp = client.post(f"/api/projects/{SLUG}/tickets/{manager['id']}/close", json={"outcome": "accepted"})
    assert resp.get_json()["closure_forced"] == ""
    assert _reload(manager)["state_reason"]["code"] == "accepte"
