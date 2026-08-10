# [desc] Conversation feature tests: an un-snippeted Read raises a Snippet enforcement warning; a covered one stays silent. [/desc]
"""Snippet coverage of a Read, observed from a real bouzecode() conversation.

Replaces the hand-built-message unit tests of get_unsnippeted_reads(): instead of
forging a `messages` list, the (mocked) model actually reads a file and we watch
the loop's own `EnforcementWarning(missing_tools=["Snippet"])` in result.events.
Nothing is mocked but the model's replies.

Turn shape matters and is deliberate:
- the read-bearing batch is always followed by a real working turn, because the
  loop defers the coverage check until the model has had its next turn (without
  that following turn the scan short-circuits and the assertions prove nothing);
- a Methodology(+Snippet) batch is meta-only — it nudges instead of closing — so
  every scenario ends on a plain, tool-call-free reply.
Each "no warning" case is paired with the warning case just below it, so the
silence is meaningful.
"""
from __future__ import annotations

import pytest

from tests.e2e_harness import bouzecode
from tests.fake_llm import MockLLM
from bouzecode.backend.agent.loop_detector import EnforcementWarning

METH = '<tool_use name="Methodology" id="m{i}"><param name="content">travail</param></tool_use>'
WORK = '<tool_use name="Bash" id="b1"><param name="command">echo suite</param></tool_use>'
CLOSE = "Termine."
# Recovery — and therefore the enforcement warning — runs when memory recovery is
# on, the production setting for a session with methodology enforced.
RECOVER = {"recover_memory": True}


@pytest.fixture
def big_file(tmp_path):
    """A file long enough (>= SNIPPET_MIN_LINES) that reading it demands a Snippet."""
    f = tmp_path / "gros_module.py"
    f.write_text("\n".join(f"line {i}" for i in range(80)), encoding="utf-8")
    return str(f).replace("\\", "/")


def _read(path):
    return f'<tool_use name="Read" id="r1"><param name="file_path">{path}</param></tool_use>'


def _snippet(params):
    return f'<tool_use name="Snippet" id="s1">{params}</tool_use>'


def _run(first_turn, second_turn):
    # CLOSE twice: when the enforcement warning DOES fire, the loop injects its
    # nudge and asks the model for one more turn, so the scenario needs a reply
    # to spare. MockLLM never requires its script to be exhausted, so the
    # no-warning cases simply stop one reply earlier.
    result = bouzecode(
        ["regarde ce module"],
        mock_llm=MockLLM([first_turn, second_turn, CLOSE, CLOSE]),
        config_overrides=RECOVER,
    )
    return [e for e in result.events
            if isinstance(e, EnforcementWarning) and "Snippet" in (e.missing_tools or [])]


# ── coverage inside the same batch ───────────────────────────────────────────

def test_read_snippeted_in_the_same_batch_raises_no_warning(big_file):
    """Lire un fichier et le snippeter dans le même tour ne déclenche aucun rappel d'enforcement."""
    warnings = _run(
        f'{METH.format(i=1)}\n{_read(big_file)}\n'
        + _snippet(f'<param name="file_path">{big_file}</param>'
                   f'<param name="ranges">[[1, 3]]</param><param name="label">tete</param>'),
        f'{METH.format(i=2)}\n{WORK}',
    )
    assert warnings == []


def test_read_snippeted_on_another_file_in_the_same_batch_warns(big_file):
    """Snippeter un autre fichier ne couvre pas la lecture : le rappel part quand même."""
    warnings = _run(
        f'{METH.format(i=1)}\n{_read(big_file)}\n'
        + _snippet('<param name="file_path">C:/ailleurs/autre.py</param>'
                   '<param name="ranges">[[1, 2]]</param>'),
        f'{METH.format(i=2)}\n{WORK}',
    )
    assert len(warnings) == 1


def test_read_discarded_in_the_same_batch_raises_no_warning(big_file):
    """Écarter explicitement la lecture (discard) dans le même tour vaut couverture."""
    warnings = _run(
        f'{METH.format(i=1)}\n{_read(big_file)}\n'
        + _snippet(f'<param name="file_path">{big_file}</param>'
                   f'<param name="discard">true</param>'),
        f'{METH.format(i=2)}\n{WORK}',
    )
    assert warnings == []


# ── coverage at the next turn (and the grace period that allows it) ──────────

def test_read_snippeted_at_the_next_turn_raises_no_warning(big_file):
    """L'agent a droit au tour suivant pour snippeter sa lecture : rien ne part entre-temps."""
    warnings = _run(
        f'{METH.format(i=1)}\n{_read(big_file)}',
        f'{METH.format(i=2)}\n'
        + _snippet(f'<param name="file_path">{big_file}</param>'
                   f'<param name="ranges">[[1, 2]]</param><param name="label">tete</param>'),
    )
    assert warnings == []


def test_read_still_uncovered_at_the_next_turn_warns(big_file):
    """Une lecture toujours pas snippetée au tour suivant déclenche un rappel d'enforcement."""
    warnings = _run(
        f'{METH.format(i=1)}\n{_read(big_file)}',
        f'{METH.format(i=2)}\n{WORK}',   # real work, but the Snippet is forgotten
    )
    assert len(warnings) == 1
