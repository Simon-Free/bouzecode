# [desc] Wake fires + digest instructs MessageAgent when a child is BLOCKED on a question. [/desc]
"""A child paused on AskUserQuestion ('attend réponse') is not terminal (busy), yet the
parent manager MUST wake to answer it — else the question is orphaned. These pure-predicate
tests lock that behaviour (bug: manager never re-invoked for an awaiting child)."""
from bouzecode.web_v2.services.work import wake


def _awaiting_child(tid="c1"):
    """Minimal ticket whose only run is paused awaiting user input."""
    return {"id": tid, "title": "profil dropdown",
            "runs": [{"agent_id": "aaa", "kind": "work", "state": "awaiting_input"}]}


def _ok_child(tid="c2"):
    return {"id": tid, "title": "done", "done": True,
            "runs": [{"agent_id": "bbb", "kind": "validate", "state": "finished", "verdict": "OK"}]}


def test_awaiting_child_is_blocked_on_question():
    assert wake.child_blocked_on_question(_awaiting_child()) is True
    assert wake.child_blocked_on_question(_ok_child()) is False


def test_parent_wakes_for_a_blocked_child_even_if_not_terminal():
    kids = [_awaiting_child()]
    sig = wake.children_signature(kids)
    # A blocked (busy) child would fail the all-terminal gate; the block-on-question gate must save it.
    assert wake.should_wake_parent(True, kids, last_signature=None, current_signature=sig) is True


def test_no_double_wake_when_signature_unchanged():
    kids = [_awaiting_child()]
    sig = wake.children_signature(kids)
    assert wake.should_wake_parent(True, kids, last_signature=sig, current_signature=sig) is False


def test_digest_tells_manager_to_answer_via_message_agent():
    digest = wake.build_wake_digest([_awaiting_child("c1")])
    assert "MessageAgent" in digest
    assert "AskUserQuestion" in digest
    assert "c1" in digest
    assert "BLOQUÉ" in digest
