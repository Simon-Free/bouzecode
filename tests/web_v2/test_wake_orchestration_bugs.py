"""Deux bugs d'orchestration réveil/finalisation des tickets parents (bug témoin 1b5860ed).

BUG1 — course « enfant en cours de lancement » : un enfant fraîchement redispatché est en
`provisioning` AVANT d'avoir un run. Sans correctif, il est ignoré du critère « tous enfants
terminaux » → le parent est finalisé trop tôt.

Finalisation : un manager LIVRÉ dont le routage est fini est clos (`closed{routage_termine}`).

Aucun unittest.mock : tickets réels dans le store isolé du test.
"""
from bouzecode.web_v2.services.work import tickets as tickets_svc
from bouzecode.web_v2.services.work import wake
from bouzecode.web_v2.services.work.fsm import etats
from bouzecode.web_v2.tests.aides_tickets import run, semer


class _FakeParent:
    def __init__(self, slug, tid):
        self.ticket_slug = slug
        self.ticket_id = tid


# ── BUG1 : un enfant en cours de lancement bloque le réveil/la finalisation du parent ──

def test_child_launching_blocks_parent_wake():
    """Le parent a fini, un enfant A est terminal, MAIS un enfant B vient d'être redispatché
    (provisioning, aucun run) : le parent ne doit PAS être réveillé (donc pas finalisé)."""
    child_terminal = {"id": "a", "parent": "mgr", "typology": "codeur", "state": etats.CLOSED,
                      "state_reason": {"code": "integre"}, "runs": [{"kind": "work"}]}
    child_launching = {"id": "b", "parent": "mgr", "typology": "codeur",
                       "state": etats.PROVISIONING}
    kids = [child_terminal, child_launching]
    assert wake.should_wake_parent(True, [child_terminal], None, "sig") is True
    assert wake.should_wake_parent(True, kids, None, "sig") is False


def test_child_launching_is_pending_predicate():
    """child_pending_launch reconnaît l'enfant en cours de lancement, ignore les autres."""
    assert wake.child_pending_launch({"state": etats.PROVISIONING}) is True
    assert wake.child_pending_launch({"state": etats.CREATED}) is False
    assert wake.child_pending_launch({"state": etats.RUNNING, "runs": [{"kind": "work"}]}) is False
    assert wake.child_pending_launch({}) is False


# ── Un manager livré dont tous les enfants ont fini est clos ──

def test_manager_is_finalized():
    semer("proj", "mgr", etats.DELIVERED, typology="manager", runs=[run("m1")])
    assert wake._finalize_noncoding_parent(_FakeParent("proj", "mgr")) is True
    frais = tickets_svc.get_ticket("proj", "mgr")
    assert (frais["state"], frais["state_reason"]["code"]) == (etats.CLOSED, "routage_termine")


def test_un_manager_arrete_n_est_pas_clos_d_office():
    semer("proj", "mgr2", etats.STOPPED, "crashed", typology="manager", runs=[run("m2")])
    assert wake._finalize_noncoding_parent(_FakeParent("proj", "mgr2")) is False
    assert tickets_svc.get_ticket("proj", "mgr2")["state"] == etats.STOPPED
