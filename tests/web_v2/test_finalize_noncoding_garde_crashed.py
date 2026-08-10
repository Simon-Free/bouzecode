"""Fix 4 — _finalize_noncoding_parent ne clôt PAS un manager planté.

Un manager (typologie non-codante) est normalement marqué done par le wake quand ses enfants
sont terminaux. Mais s'il a réellement planté (crashed), il doit rester visible 'planté' (en
attente d'action) plutôt que d'être masqué en 'terminé'. Fakes purs, aucun unittest.mock.
"""
from bouzecode.web_v2.services.work import wake
from bouzecode.web_v2.services.work import tickets as tickets_svc
from bouzecode.web_v2.services.work import _persistence
from bouzecode.web_v2.services.work import workflow
from bouzecode.web_v2.services.work import reaper


class _FakeParent:
    def __init__(self, slug, tid):
        self.ticket_slug = slug
        self.ticket_id = tid


def _noncoding_typology() -> str:
    return sorted(workflow.NON_CODING_TYPOLOGIES)[0]


def test_manager_crashed_reste_plante(tmp_path, monkeypatch):
    reaped: list = []
    monkeypatch.setattr(_persistence, "TICKETS_DIR", tmp_path)
    monkeypatch.setattr(tickets_svc, "TICKETS_DIR", tmp_path)
    monkeypatch.setattr(reaper, "reap_ticket", lambda slug, ticket: reaped.append(ticket["id"]))

    ticket = {"id": "m1", "typology": _noncoding_typology(), "crashed": True}
    _persistence._save("proj", [ticket])

    result = wake._finalize_noncoding_parent(_FakeParent("proj", "m1"))

    assert result is False, "un manager planté ne doit pas être finalisé"
    fresh = tickets_svc.get_ticket("proj", "m1")
    assert not fresh.get("done"), "done posé sur un manager planté"
    assert reaped == [], "reap_ticket appelé sur un manager planté"
    assert tickets_svc.derive_status(fresh) == "planté"


def test_manager_non_crashed_est_bien_finalise(tmp_path, monkeypatch):
    """Contrôle : sans crash, la clôture normale du manager fonctionne toujours (done + reap)."""
    reaped: list = []
    monkeypatch.setattr(_persistence, "TICKETS_DIR", tmp_path)
    monkeypatch.setattr(tickets_svc, "TICKETS_DIR", tmp_path)
    monkeypatch.setattr(reaper, "reap_ticket", lambda slug, ticket: reaped.append(ticket["id"]))

    ticket = {"id": "m2", "typology": _noncoding_typology()}
    _persistence._save("proj", [ticket])

    result = wake._finalize_noncoding_parent(_FakeParent("proj", "m2"))

    assert result is True
    assert tickets_svc.get_ticket("proj", "m2").get("done") is True
    assert reaped == ["m2"]
