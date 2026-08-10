# [desc] Feature tests: consecutive meta-only turns close the session only when they stop bringing anything new. [/desc]
"""The anti-loop cap must fire on a STUCK model, not on a working one.

Observed in production (2026-07-30): an agent read 7 slide images, then
spent two bookkeeping turns discarding stale snippets and writing its execution
plan. Three consecutive meta-only turns tripped the cap, the session closed with
`meta_only_cap` and no FinalAnswer, and the user got an empty answer — while the
agent was demonstrably advancing (a different plan each turn).

The signal of "stuck" is repetition, not the mere fact of being meta-only. These
tests pin both halves: an advancing agent keeps going, a repeating one is still
stopped, and a model that writes forever-new notes still terminates on the hard
backstop.
"""
from tests.e2e_harness import bouzecode
from tests.fake_llm import MockLLM

BASH = '<tool_use name="Bash" id="b1"><param name="command">echo travail</param></tool_use>'
NO_TEST_ENFORCE = {"test_enforcement": False}


def _meth(content: str, tid: str = "m1") -> str:
    return (f'<tool_use name="Methodology" id="{tid}">'
            f'<param name="content">{content}</param></tool_use>')


def _snippet_discard(tool_id: str, sid: str) -> str:
    return (f'<tool_use name="Snippet" id="{sid}">'
            f'<param name="tool_id">{tool_id}</param>'
            f'<param name="discard">true</param></tool_use>')


def test_advancing_meta_turns_do_not_close_the_session():
    """Each meta-only turn carries a NEW plan → the agent is working, not stuck."""
    mock = MockLLM([
        _meth("etape 1: lire les 7 images"),
        _meth("etape 2: extraire les valeurs chiffrees"),
        _meth("etape 3: reconstruire les graphiques"),
        f'{_meth("etape 4: execution")}\n{BASH}',
        "termine.",
    ])
    result = bouzecode(["refais les graphiques"], mock_llm=mock,
                       config_overrides=NO_TEST_ENFORCE)

    assert result.state.close_reason != "meta_only_cap"
    bash_results = [m for m in result.messages
                    if m.get("role") == "tool" and m.get("name") == "Bash"]
    assert bash_results, "the agent must have reached its execution turn"


def test_snippet_bookkeeping_then_plan_does_not_close():
    """The exact production sequence: snippet discards, then the plan."""
    mock = MockLLM([
        f'{_snippet_discard("c3", "s1")}\n{_snippet_discard("c4", "s2")}',
        f'{_snippet_discard("c5", "s3")}\n{_snippet_discard("c6", "s4")}',
        _meth("plan de reconstruction des 7 graphiques"),
        f'{_meth("execution")}\n{BASH}',
        "termine.",
    ])
    result = bouzecode(["refais les graphiques"], mock_llm=mock,
                       config_overrides=NO_TEST_ENFORCE)

    assert result.state.close_reason != "meta_only_cap"
    bash_results = [m for m in result.messages
                    if m.get("role") == "tool" and m.get("name") == "Bash"]
    assert bash_results, "the agent must have reached its execution turn"


def test_repeated_identical_meta_turns_still_close():
    """A model rewriting the SAME note is stuck — the guard must still fire."""
    same = _meth("plan")
    mock = MockLLM([same, same, same, same])
    result = bouzecode(["fais la tache"], mock_llm=mock,
                       config_overrides=NO_TEST_ENFORCE)

    assert result.state.close_reason == "meta_only_cap"


def test_endless_new_notes_still_terminate_on_the_backstop():
    """Forever-new notes must not loop forever: the hard cap bounds the session."""
    mock = MockLLM([_meth(f"note numero {i}") for i in range(20)])
    result = bouzecode(["fais la tache"], mock_llm=mock,
                       config_overrides=NO_TEST_ENFORCE)

    assert result.state.close_reason == "meta_only_cap"
    assert mock.call_index < 20, "the backstop must close before the script runs out"
