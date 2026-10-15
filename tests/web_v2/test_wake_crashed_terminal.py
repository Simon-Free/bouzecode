# [desc] Un enfant ARRÊTÉ (ou intégré) est vu TERMINAL par le réveil du parent : l'issue se lit dans `ticket.state`. Prédicats purs. [/desc]
"""Le réveil du parent lit l'état persisté de ses enfants (lot L2) : arrêté, livré, intégré,
abandonné… = une issue ; en vol = pas encore. Zéro agent LLM."""
from bouzecode.web_v2.services.work import wake
from bouzecode.web_v2.services.work.fsm import etats


def _enfant(tid, state, code=None, **extra):
    return {"id": tid, "title": "T", "prompt": "p", "state": state,
            "state_reason": {"code": code} if code else None,
            "runs": [{"agent_id": "a" * 12, "kind": "work"}], **extra}


def _crashed(tid="1"):
    return _enfant(tid, etats.STOPPED, "crashed")


def _merged(tid="1"):
    return _enfant(tid, etats.CLOSED, "integre")


def test_busy_ticket_is_not_terminal():
    assert wake.ticket_terminal(_enfant("1", etats.RUNNING)) is False
    assert wake.ticket_terminal(_enfant("1", etats.PROVISIONING)) is False


def test_crashed_child_is_terminal_and_wakes_parent():
    c = _crashed()
    assert wake.ticket_terminal(c) is True
    sig = wake.children_signature([c])
    assert wake.should_wake_parent(True, [c], None, sig) is True


def test_mixed_terminal_children_all_wake():
    kids = [_merged("1"), _crashed("3")]
    assert wake.should_wake_parent(True, kids, None, wake.children_signature(kids)) is True


def test_digest_distinguishes_ok_crashed():
    digest = wake.build_wake_digest([_merged("1") | {"title": "A"}, _crashed("3") | {"title": "C"}])
    assert "Ticket 1 « A » : OK (mergé)" in digest
    assert "Ticket 3 « C » : CRASHED" in digest


def test_outcome_labels_are_distinct():
    assert wake.ticket_outcome(_merged()) == "OK (mergé)"
    assert wake.ticket_outcome(_crashed()) == "CRASHED"
    assert wake.ticket_outcome(_enfant("1", etats.STOPPED, "killed")) == "ARRÊTÉ (killed)"
    assert wake.ticket_outcome(_enfant("1", etats.IDLE_NO_DELIVERY, "max_turns_exceeded")) == \
        "ARRÊTÉ SANS LIVRER (max_turns_exceeded)"
