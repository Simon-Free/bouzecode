"""Fix 4 — _finalize_noncoding_parent ne clôt PAS un manager planté.

Un manager (typologie non-codante) est normalement clos par le wake quand ses enfants sont
terminaux. Mais s'il a réellement planté (`stopped`), il doit rester visible « planté » (en
attente d'action) plutôt que d'être masqué en « terminé ». Aucun unittest.mock.
"""
from bouzecode.web_v2.services.work import constats, wake
from bouzecode.web_v2.services.work import tickets as tickets_svc
from bouzecode.web_v2.services.work.fsm import etats
from bouzecode.web_v2.tests.aides_tickets import run, semer


class _FakeParent:
    def __init__(self, slug, tid):
        self.ticket_slug = slug
        self.ticket_id = tid


def _noncoding_typology() -> str:
    return sorted(constats.NON_CODING_TYPOLOGIES)[0]


def test_manager_crashed_reste_plante():
    semer("proj", "m1", etats.STOPPED, "crashed", typology=_noncoding_typology(),
          runs=[run("a1")])
    assert wake._finalize_noncoding_parent(_FakeParent("proj", "m1")) is False
    fresh = tickets_svc.get_ticket("proj", "m1")
    assert fresh["state"] == etats.STOPPED
    assert tickets_svc.derive_status(fresh) == "planté"


def test_manager_non_crashed_est_bien_finalise():
    """Contrôle : un manager livré est clos normalement (`closed`)."""
    semer("proj", "m2", etats.DELIVERED, typology=_noncoding_typology(), runs=[run("a2")])
    assert wake._finalize_noncoding_parent(_FakeParent("proj", "m2")) is True
    assert tickets_svc.get_ticket("proj", "m2")["state"] == etats.CLOSED
