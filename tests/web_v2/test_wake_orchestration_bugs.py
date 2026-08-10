"""Deux bugs d'orchestration réveil/finalisation des tickets parents (bug témoin 1b5860ed).

BUG1 — course « enfant en cours de lancement » : un enfant fraîchement redispatché est en
`launching` AVANT d'avoir un run (add_run retire le flag). Sans correctif, il est ignoré du
critère « tous enfants terminaux » → le parent est finalisé `done` trop tôt.

BUG2 — verdict manager ignoré : un manager qui rend `VERDICT: KO` ne doit PAS être clos
`done`. La typologie `manager` doit être parsée (verdict remonté) et sa conséquence câblée
côté finalisation.

Fakes purs, aucun unittest.mock : tickets réels écrits dans un tmp dir, reaper injecté.
"""
import json

from bouzecode.web_v2.services.work import wake
from bouzecode.web_v2.services.work import tickets as tickets_svc
from bouzecode.web_v2.services.work import _persistence
from bouzecode.web_v2.services.work import workflow
from bouzecode.web_v2.services.work import reaper


class _FakeParent:
    def __init__(self, slug, tid):
        self.ticket_slug = slug
        self.ticket_id = tid


def _manager_typology() -> str:
    return "manager"


# ── BUG1 : un enfant en cours de lancement bloque le réveil/la finalisation du parent ──

def test_child_launching_blocks_parent_wake():
    """Le parent a fini, un enfant A est terminal, MAIS un enfant B vient d'être redispatché
    (launching, aucun run) : le parent ne doit PAS être réveillé (donc pas finalisé)."""
    child_terminal = {
        "id": "a", "parent": "mgr", "typology": "codeur",
        "runs": [{"kind": "work", "state": "done"}],
        "worktree": {"state": "integrated"},
    }
    child_launching = {
        "id": "b", "parent": "mgr", "typology": "codeur",
        "launching": True,  # set_launching posé AVANT le premier run
    }
    kids = [child_terminal, child_launching]

    # Sans l'enfant launching, la signature neuve réveillerait le parent.
    assert wake.should_wake_parent(True, [child_terminal], None, "sig") is True
    # Avec l'enfant en cours de lancement, le réveil est bloqué.
    assert wake.should_wake_parent(True, kids, None, "sig") is False


def test_child_launching_is_pending_predicate():
    """child_pending_launch reconnaît l'enfant en cours de lancement, ignore les autres."""
    assert wake.child_pending_launch({"launching": True}) is True
    assert wake.child_pending_launch({"launching": False}) is False
    assert wake.child_pending_launch({"runs": [{"kind": "work"}]}) is False
    assert wake.child_pending_launch({}) is False


# ── BUG2 : un manager qui rend VERDICT: KO n'est pas finalisé done ──

def test_manager_verdict_ko_not_finalized(tmp_path, monkeypatch):
    """Un manager avec un run work portant verdict=KO ne doit PAS être stampé done : il reste
    en attente (observable : ticket non 'done', jamais fauché)."""
    reaped: list = []
    monkeypatch.setattr(reaper, "reap_ticket", lambda slug, ticket: reaped.append(ticket["id"]))

    monkeypatch.setattr(_persistence, "TICKETS_DIR", tmp_path)
    monkeypatch.setattr(tickets_svc, "TICKETS_DIR", tmp_path)
    ticket = {
        "id": "mgr", "typology": _manager_typology(),
        "runs": [{"kind": "work", "typology": "manager", "verdict": "KO", "state": "done"}],
    }
    _persistence._save("proj", [ticket])

    finalized = wake._finalize_noncoding_parent(_FakeParent("proj", "mgr"))

    assert finalized is False
    stored = tickets_svc.get_ticket("proj", "mgr")
    assert not stored.get("done")
    assert reaped == []  # jamais fauché


def test_manager_verdict_ok_is_finalized(tmp_path, monkeypatch):
    """Contrôle miroir : un manager avec verdict OK (ou sans verdict) est bien finalisé done."""
    reaped: list = []
    monkeypatch.setattr(reaper, "reap_ticket", lambda slug, ticket: reaped.append(ticket["id"]))

    monkeypatch.setattr(_persistence, "TICKETS_DIR", tmp_path)
    monkeypatch.setattr(tickets_svc, "TICKETS_DIR", tmp_path)
    ticket = {
        "id": "mgr", "typology": _manager_typology(),
        "runs": [{"kind": "work", "typology": "manager", "verdict": "OK", "state": "done"}],
    }
    _persistence._save("proj", [ticket])

    finalized = wake._finalize_noncoding_parent(_FakeParent("proj", "mgr"))

    assert finalized is True
    assert tickets_svc.get_ticket("proj", "mgr").get("done") is True
    assert reaped == ["mgr"]


def test_manager_typology_carries_verdict():
    """La typologie `manager` est bien prise en compte par le parsing de verdict :
    _run_carries_verdict autorise le tail-read d'un run work de manager."""
    run_manager = {"kind": "work", "typology": "manager"}
    assert wake.tickets_svc._run_carries_verdict(run_manager) is True
    # Un run de dev classique (typologie non listée) reste ignoré.
    run_dev = {"kind": "work", "typology": "codeur"}
    assert wake.tickets_svc._run_carries_verdict(run_dev) is False
