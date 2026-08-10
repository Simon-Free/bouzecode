"""Anti-paralysis nudge: a streak of exploration-only turns gets a system event
every 4th turn; any producing turn resets the streak. Observed motivation:
flash reading 40 turns / 0 Write until timeout on exploratory tickets."""
import pytest

from tests.e2e_harness import bouzecode
from tests.fake_llm import MockLLM

# The read-only nudge/abort was intentionally disabled in commit 8de361c: the
# streak is now tracked for observability only (loop_turn.py:591 "no abort/nudge",
# _get_paralysis_abort_after is dead code). These tests assert the removed
# behaviour — skipped until/unless the feature is restored.
pytestmark = pytest.mark.skip(
    reason="read-only nudge/abort disabled — observability only (loop_turn.py:591)"
)

METH = '<tool_use name="Methodology" id="m{n}"><param name="content">ok</param></tool_use>'


def _read_turn(n: int) -> str:
    return (METH.replace("{n}", str(n))
            + f'<tool_use name="Glob" id="g{n}"><param name="pattern">*.py</param></tool_use>')


def _nudges(result) -> list[str]:
    return [str(m.get("content", "")) for m in result.messages
            if m.get("role") == "user"
            and "tours d'exploration consécutifs" in str(m.get("content", ""))]


def test_four_readonly_turns_trigger_nudge():
    mock = MockLLM([_read_turn(n) for n in range(1, 6)] + ["réponse finale.\n" + METH.replace("{n}", "9")])
    result = bouzecode(["analyse le repo"], mock_llm=mock,
                       config_overrides={"test_enforcement": False, "detect_loops": False})
    assert _nudges(result), "4 consecutive read-only turns must trigger the nudge"


def test_twelve_readonly_turns_abort_session():
    """Fast-fail: at paralysis_abort_after consecutive read-only turns the
    session closes instead of burning the whole ticket timeout."""
    mock = MockLLM([_read_turn(n) for n in range(1, 20)])
    result = bouzecode(["analyse le repo"], mock_llm=mock,
                       config_overrides={"test_enforcement": False, "detect_loops": False})
    assert mock.call_count == 12, "session must abort exactly at the 12th read-only turn"
    aborts = [m for m in result.messages if "paralysie d'analyse" in str(m.get("content", ""))]
    assert aborts


def test_producing_turn_resets_streak():
    write = ('<tool_use name="Write" id="w1"><param name="file_path">out.txt</param>'
             '<param name="content">x</param></tool_use>')
    turns = [_read_turn(1), _read_turn(2), _read_turn(3),
             METH.replace("{n}", "4") + write,   # production resets the streak
             _read_turn(5), _read_turn(6), _read_turn(7),
             "fini.\n" + METH.replace("{n}", "8")]
    mock = MockLLM(turns)
    result = bouzecode(["tâche"], mock_llm=mock,
                       config_overrides={"test_enforcement": False, "detect_loops": False})
    assert not _nudges(result), "a Write inside the streak must reset the counter"
