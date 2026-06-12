# [desc] Tests empty-reply continuation nudges, nudge cap, methodology recovery, and premature close behavior. [/desc]
"""Repro of the deepseek-v4-pro premature close (2026-06-10): the model EOSes on a
wire ending in tool results (empty reply), right after its Methodology was already
recorded. Flow: nudge continuation (max 2) ; au-delà, la session se clôt — le tour
de conformité (Fallback B) est supprimé depuis le ticket 82fe4b87, pas de fallback."""
from tests.e2e_harness import bouzecode
from tests.fake_llm import MockLLM

METH = '<tool_use name="Methodology" id="m1"><param name="content">plan ok</param></tool_use>'
WORK = (
    f"{METH}\n"
    '<tool_use name="Bash" id="b1"><param name="command">echo hi</param></tool_use>'
)


def _user_contents(result):
    return [str(m.get("content", "")) for m in result.messages if m.get("role") == "user"]


def test_empty_reply_after_methodology_batch_gets_continuation_nudge():
    mock = MockLLM([
        WORK,        # turn 1: real work + Methodology recorded
        "",          # turn 2: totally empty reply (provider EOS glitch)
        f"fini.\n{METH}",  # turn 3: unstuck — final answer closes
    ])
    result = bouzecode(["fais le travail"], mock_llm=mock)
    users = _user_contents(result)
    assert any("réponse vide reçue" in c for c in users), users
    assert not any("ENFORCEMENT" in c for c in users), users
    assert "fini" in result.last_reply


def test_empty_reply_nudge_capped_then_close():
    mock = MockLLM([
        WORK,              # turn 1: Methodology recorded
        "", "", "",        # turns 2-4: model keeps replying empty
    ])
    result = bouzecode(["fais le travail"], mock_llm=mock)
    users = _user_contents(result)
    nudges = [c for c in users if "réponse vide reçue" in c]
    assert len(nudges) == 2, users  # capped at 2, puis la session se clôt
    assert not any("ENFORCEMENT" in c for c in users), users  # plus de tour de conformité
    assert mock.call_count == 4


def test_methodology_recovery_adds_proactive_continuation_message(monkeypatch):
    """After an out-of-band Methodology recovery, the next wire carries a user
    continuation message — pro EOSes an empty reply on that state otherwise."""
    from bouzecode.backend.agent import enforcement_call
    monkeypatch.setattr(enforcement_call, "recover_methodology",
                        lambda state, config, ctx: {"id": "rm", "name": "Methodology",
                                                    "input": {"content": "recovered"}})
    glob = '<tool_use name="Glob" id="g1"><param name="pattern">**/*.py</param></tool_use>'
    mock = MockLLM([glob, f"Fini.\n{METH}"])
    result = bouzecode(["go"], mock_llm=mock, config_overrides={"recover_memory": True})
    users = _user_contents(result)
    assert any("Methodology récupérée" in c for c in users), users
    assert "Fini" in result.last_reply


def test_no_continuation_message_when_methodology_emitted():
    """A turn that emits its own Methodology needs no recovery, hence no nudge."""
    mock = MockLLM([WORK, f"Fini.\n{METH}"])
    result = bouzecode(["go"], mock_llm=mock, config_overrides={"recover_memory": True})
    users = _user_contents(result)
    assert not any("Methodology récupérée" in c for c in users), users


def test_empty_reply_without_recorded_methodology_closes():
    mock = MockLLM([
        '<tool_use name="Bash" id="b1"><param name="command">echo hi</param></tool_use>',
        "",                # empty reply, NO Methodology recorded → clôture directe
    ])
    result = bouzecode(["fais le travail"], mock_llm=mock)
    users = _user_contents(result)
    assert not any("ENFORCEMENT" in c for c in users), users  # pas de bounce
    assert not any("réponse vide reçue" in c for c in users), users  # nudge réservé au cas Methodology déjà enregistrée
    assert mock.call_count == 2
