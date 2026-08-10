# [desc] Un manager dont un enfant a planté sans rien livrer ne peut pas être enregistré « terminé ». [/desc]
"""Le garde-fou de clôture d'un manager (cas réel beefcafe / enfant deadbeef).

Histoire : un manager dispatche des enfants, ferme son tour sur « VERDICT: OK », et le
watchdog veut le clôturer. Tant qu'un enfant a planté sans écrire une ligne, la clôture est
REFUSÉE, dite à l'écran et tracée sur le ticket ; dès que l'enfant livre (ou qu'un humain
tranche), elle repart. Store SQLite réel en tmp (fixture autouse), aucun mock.
"""
from __future__ import annotations

import pytest

from bouzecode.web_v2.services.work import closure_guard, wake
from bouzecode.web_v2.services.work import tickets as tickets_svc

SLUG = "projet-du-manager"
MANAGER_AGENT = "mgr-1"


class _ParentAgent:
    """Ce que `wake` connaît du manager : son ticket. (Le vrai `runner.Agent` en dit plus.)"""

    def __init__(self, slug: str, ticket_id: str):
        self.ticket_slug, self.ticket_id = slug, ticket_id


@pytest.fixture()
def manager() -> dict:
    ticket = tickets_svc.create_ticket(SLUG, "pilotage de l'intégration", "orchestre le portage")
    ticket["typology"] = "manager"
    tickets_svc.update_ticket(SLUG, ticket)
    tickets_svc.add_run(SLUG, ticket, MANAGER_AGENT, "work", "opus", typology="manager")
    ticket["runs"][0]["verdict"] = "OK"  # le manager s'est auto-déclaré OK
    tickets_svc.update_ticket(SLUG, ticket)
    return ticket


def _child(title: str, agent_id: str, *, delivered: bool, **flags) -> dict:
    ticket = tickets_svc.create_ticket(SLUG, title, "fais le travail")
    ticket["parent"] = MANAGER_AGENT
    tickets_svc.update_ticket(SLUG, ticket)
    tickets_svc.add_run(SLUG, ticket, agent_id, "work", "opus", typology="coder")
    if delivered:
        tickets_svc.mark_run_completed(SLUG, ticket, agent_id)
    ticket.update(flags)  # après add_run, qui purge les drapeaux terminaux (dont `crashed`)
    tickets_svc.update_ticket(SLUG, ticket)
    return ticket


def _finalize(manager: dict, children: list[dict]) -> bool:
    return wake._finalize_noncoding_parent(_ParentAgent(SLUG, manager["id"]), children)


def _reload(ticket: dict) -> dict:
    return tickets_svc.get_ticket(SLUG, ticket["id"])


# ── (a) l'enfant planté sans livraison gèle la clôture, et ça se voit ────────────────────

def test_a_manager_is_not_closed_while_a_child_crashed_without_delivering(manager):
    """Un enfant planté sans un seul fichier produit empêche son manager d'être « terminé »."""
    crashed = _child("stockage azure", "coder-mort", delivered=False, crashed=True)
    children = [_child("inventaire", "coder-1", delivered=True), crashed]

    assert _finalize(manager, children) is False

    stored = _reload(manager)
    assert not stored.get("done"), "le manager a été stampé terminé malgré un enfant planté"
    assert tickets_svc.derive_status(stored) == "clôture bloquée"


def test_a_the_refusal_names_the_guilty_child_and_the_way_out(manager):
    """Le refus laisse une trace lisible : l'enfant fautif, pourquoi, et comment débloquer."""
    crashed = _child("stockage azure", "coder-mort", delivered=False, crashed=True)

    _finalize(manager, [crashed])

    trace = _reload(manager)["comments"][-1]["text"]
    assert crashed["id"] in trace
    assert "Clôture BLOQUÉE" in trace
    assert "aucune livraison" in trace
    assert f"/api/tickets/{SLUG}/{manager['id']}/done" in trace


def test_a_a_repeated_watchdog_tick_does_not_repeat_the_trace(manager):
    """Le blocage se dit UNE fois : le watchdog qui repasse toutes les 8 s ne spamme pas."""
    crashed = _child("stockage azure", "coder-mort", delivered=False, crashed=True)

    for _ in range(4):
        _finalize(manager, [crashed])

    assert len(_reload(manager)["comments"]) == 1


def test_a_a_child_dead_before_the_crash_flag_is_stamped_also_blocks(manager):
    """Même sans le drapeau `crashed` (debounce du watchdog), un enfant qui n'a rien livré
    bloque : sinon la fausse clôture passait simplement deux ticks plus tôt."""
    silent = _child("stockage azure", "coder-muet", delivered=False)

    assert _finalize(manager, [silent]) is False
    assert tickets_svc.derive_status(_reload(manager)) == "clôture bloquée"


# ── (b) la clôture légitime n'est pas cassée ─────────────────────────────────────────────

def test_b_a_manager_whose_children_all_delivered_is_closed_normally(manager):
    """Tous les enfants ont livré : le manager est clôturé comme avant le garde-fou."""
    children = [_child("inventaire", "coder-1", delivered=True),
                _child("assemblage", "coder-2", delivered=True)]

    assert _finalize(manager, children) is True

    stored = _reload(manager)
    assert stored["done"] is True
    assert tickets_svc.derive_status(stored) == "terminé"


def test_b_a_child_that_delivered_after_crashing_stops_blocking(manager):
    """L'enfant relancé qui livre enfin lève le blocage — et le statut cesse de le dire."""
    child = _child("stockage azure", "coder-mort", delivered=False, crashed=True)
    assert _finalize(manager, [child]) is False

    relaunched = _child("stockage azure", "coder-repris", delivered=True)
    relaunched["id"] = child["id"]  # même ticket, nouveau run : il a livré depuis

    assert _finalize(manager, [relaunched]) is True
    stored = _reload(manager)
    assert stored["done"] is True
    assert "closure_blocked" not in stored


# ── (c) un enfant abandonné ne gèle pas son parent pour l'éternité ───────────────────────

@pytest.mark.parametrize("excuse", [
    {"archived": True},   # retrait volontaire du board par l'utilisateur
    {"done": True},       # acquitté à la main : l'humain a déjà statué sur cet enfant
    {"reaped": True},     # worktree nettoyé : plus relançable, la suite vit ailleurs
])
def test_c_an_abandoned_child_does_not_freeze_its_parent(manager, excuse):
    """Un enfant archivé, acquitté ou fauché ne bloque pas son manager, même planté."""
    child = _child("stockage azure", "coder-mort", delivered=False, crashed=True, **excuse)

    assert _finalize(manager, [child]) is True
    assert _reload(manager)["done"] is True


def test_c_a_child_that_never_started_does_not_block(manager):
    """Un enfant créé mais jamais lancé (aucun run) ne peut rien avoir livré : il ne bloque pas."""
    never_launched = tickets_svc.create_ticket(SLUG, "jamais lancé", "…")

    assert _finalize(manager, [never_launched]) is True


# ── (d) la porte de sortie humaine ───────────────────────────────────────────────────────

@pytest.fixture()
def client():
    from bouzecode.web_v2.app import create_app
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as test_client:
        yield test_client


def test_d_a_human_can_force_the_closure_and_it_is_traced(manager, client):
    """L'utilisateur peut clore malgré tout via le bouton Terminé : c'est acté et tracé."""
    crashed = _child("stockage azure", "coder-mort", delivered=False, crashed=True)
    _finalize(manager, [crashed])

    resp = client.post(f"/api/tickets/{SLUG}/{manager['id']}/done")

    assert resp.status_code == 200
    assert resp.get_json() == {"done": True, "closure_forced": crashed["id"]}
    stored = _reload(manager)
    assert tickets_svc.derive_status(stored) == "terminé"
    assert "Clôture FORCÉE" in stored["comments"][-1]["text"]
    assert crashed["id"] in stored["comments"][-1]["text"]


def test_d_a_forced_closure_is_never_re_blocked_by_the_watchdog(manager, client):
    """Une fois forcée, la clôture n'est plus remise en cause à chaque tick du watchdog."""
    crashed = _child("stockage azure", "coder-mort", delivered=False, crashed=True)
    _finalize(manager, [crashed])
    client.post(f"/api/tickets/{SLUG}/{manager['id']}/done")

    assert closure_guard.refuse_closure(SLUG, _reload(manager), [crashed]) == []


def test_d_closing_an_unblocked_ticket_forces_nothing(manager, client):
    """Le bouton Terminé d'un ticket non bloqué ne prétend rien avoir forcé."""
    resp = client.post(f"/api/tickets/{SLUG}/{manager['id']}/done")

    assert resp.get_json() == {"done": True, "closure_forced": ""}
    assert "closure_forced" not in _reload(manager)
