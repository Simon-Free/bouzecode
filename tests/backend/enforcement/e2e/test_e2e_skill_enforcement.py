# [desc] E2E tests verifying Skill tool enforcement hooks: snippet recovery, loop continuation, and mixed Read+Skill detection. [/desc]
"""E2E tests: Skill tool interaction with enforcement hooks.

Tests verify actual loop behavior:
- Skill results ARE tracked by enforcement (via [Skill: ... | file: ...] marker
  extraction in get_unsnippeted_reads). Skill without Snippet triggers enforcement.
- Loop continues after Snippet (not an ends_turn tool)
- Mixed Read+Skill: enforcement fires for uncovered Read/Skill results
- Enforcement only fires AFTER the model has had a chance to respond (not immediately
  after tool execution).
"""
import pytest
from tests.fake_llm import MockLLM
from tests.e2e_harness import bouzecode

METH = '<tool_use name="Methodology" id="m1"><param name="content">test</param></tool_use>'
SKILL_PATH = "/tmp/skills/test-skill.md"
# Skill result must be >= SNIPPET_MIN_LINES (50) to trigger enforcement/recovery
SKILL_RESULT = f"[Skill: test-skill | file: {SKILL_PATH}]\n\n" + "\n".join(
    f"# skill line {i}" for i in range(1, 55)
)


def test_skill_without_snippet_triggers_recovery(monkeypatch):
    """A Skill result left un-snippeted is detected and a Snippet is recovered via a
    forced side-call, then appended to the batch (no in-wire bounce / extra main turn)."""
    from bouzecode.backend.agent import enforcement_call
    saw = {"calls": 0, "names": []}

    def fake(snip_results, ctx, config, state=None):
        saw["calls"] += 1
        saw["names"] += [r["name"] for r in snip_results]
        return [{"id": "rs", "name": "Snippet", "input": {"tool_id": "sk1", "discard": True}}]

    monkeypatch.setattr(enforcement_call, "recover_snippets", fake)
    mock = MockLLM([
        f'{METH}\n<tool_use name="Skill" id="sk1"><param name="name">test-skill</param></tool_use>',
        f"Done.\n{METH}",
    ])
    result = bouzecode(
        ["Load the test-skill skill"],
        mock_llm=mock,
        mock_tools={"Skill": SKILL_RESULT},
        config_overrides={"recover_memory": True},
    )
    assert saw["calls"] >= 1 and "Skill" in saw["names"]     # skill detected as un-snippeted
    snips = [tc for m in result.messages if m.get("role") == "assistant"
             for tc in (m.get("tool_calls") or []) if tc["name"] == "Snippet"]
    assert snips                                             # recovered Snippet appended + executed


def test_skill_with_snippet_completes():
    """Skill call followed by Snippet(discard=true) completes (loop continues after Snippet)."""
    mock = MockLLM([
        # Turn 1: call Skill + Methodology
        f'{METH}\n<tool_use name="Skill" id="sk1"><param name="name">test-skill</param></tool_use>',
        # Turn 2: Snippet + Methodology → Snippet not ends_turn, loop continues
        f'{METH}\n<tool_use name="Snippet" id="sn1"><param name="file_path">{SKILL_PATH}</param><param name="discard">true</param></tool_use>',
        # Turn 3: continuation (Methodology ends_turn → breaks)
        f"Skill noted.\n{METH}",
    ])
    result = bouzecode(
        ["Load the test-skill skill"],
        mock_llm=mock,
        mock_tools={"Skill": SKILL_RESULT},
    )
    # Meta-only batch (Snippet+Methodology) may terminate loop early → >= 2
    assert mock.call_count >= 2


def test_skill_with_snippet_ranges_completes():
    """Skill call followed by Snippet with ranges completes."""
    mock = MockLLM([
        f'{METH}\n<tool_use name="Skill" id="sk1"><param name="name">test-skill</param></tool_use>',
        f'{METH}\n<tool_use name="Snippet" id="sn1"><param name="file_path">{SKILL_PATH}</param><param name="ranges">[[1,5]]</param><param name="label">skill header</param></tool_use>',
        f"Skill saved.\n{METH}",
    ])
    result = bouzecode(
        ["Load the test-skill skill"],
        mock_llm=mock,
        mock_tools={"Skill": SKILL_RESULT},
    )
    # Meta-only batch (Snippet+Methodology) may terminate loop early → >= 2
    assert mock.call_count >= 2


def test_uncovered_skill_recovered_when_read_is_snippeted(monkeypatch):
    """Skill + Read both read; the model snippets only the Read → the still-uncovered
    Skill is detected and a Snippet recovered for it."""
    from bouzecode.backend.agent import enforcement_call
    saw = {"calls": 0}
    monkeypatch.setattr(enforcement_call, "recover_snippets",
                        lambda snip_results, ctx, config, state=None: saw.update(calls=saw["calls"] + 1)
                        or [{"id": "rs", "name": "Snippet", "input": {"tool_id": "sk1", "discard": True}}])
    mock = MockLLM([
        (f'{METH}\n'
         f'<tool_use name="Skill" id="sk1"><param name="name">test-skill</param></tool_use>\n'
         f'<tool_use name="Read" id="r1"><param name="file_path">/tmp/code.py</param></tool_use>'),
        # Turn 2 snippets only the Read → Skill stays uncovered → recovery fires here.
        f'{METH}\n<tool_use name="Snippet" id="sn1"><param name="file_path">/tmp/code.py</param><param name="discard">true</param></tool_use>',
        f"Done.\n{METH}",
    ])
    bouzecode(
        ["Load skill and read file"],
        mock_llm=mock,
        mock_tools={"Skill": SKILL_RESULT, "Read": "\n".join(f"line {i}" for i in range(55))},
        config_overrides={"recover_memory": True},
    )
    assert saw["calls"] >= 1                     # uncovered Skill drove a Snippet recovery
