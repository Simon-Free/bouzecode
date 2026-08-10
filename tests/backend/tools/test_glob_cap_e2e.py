# [desc] Conversation tests: a Glob matching far more files than the cap returns the cap, reports the true total, and never fails. [/desc]
"""A wide Glob answers short instead of answering huge — and never refuses.

An unfiltered `Glob("**/*.md")` used to dump up to 500 paths in one tool result
(~8 000 tokens). The fix is a CAP, not a guard: the call always succeeds, it just
prints the first `GLOB_CAP` paths, says how many matched in total, and rolls the rest
up by directory so the agent can still see where they live and narrow the search
itself.

Note on counting: `_glob` also reports the session's `temp=True` scratch files, a
process-wide registry other tests populate. The assertions below are therefore written
on invariants that hold whatever else sits in that registry — shown == cap, and
total == shown + hidden — never on a raw line count.
"""
from __future__ import annotations

import re

from bouzecode.backend.tools.ops.glob_cap import GLOB_CAP
from tests.e2e_harness import bouzecode
from tests.fake_llm import MockLLM

METH = '<tool_use name="Methodology" id="m1"><param name="content">ok</param></tool_use>'
CLOSE = "C'est fait."
_TOTAL_RE = re.compile(r"\[Glob: (\d+) files matched, showing the first (\d+)")
_HIDDEN_RE = re.compile(r"The (\d+) paths not shown")


def _tree(root, per_dir, dirs=("alpha", "beta", "gamma")):
    """Create `per_dir` .py files in each of `dirs` under `root`; return the count."""
    for d in dirs:
        (root / d).mkdir(parents=True, exist_ok=True)
        for i in range(per_dir):
            (root / d / f"mod_{i:03d}.py").write_text("x = 1\n", encoding="utf-8")
    return per_dir * len(dirs)


def _glob_result(root, pattern="*.py"):
    mock = MockLLM([
        f'{METH}\n<tool_use name="Glob" id="g1">'
        f'<param name="pattern">{pattern}</param>'
        f'<param name="path">{root.as_posix()}</param></tool_use>',
        CLOSE,
    ])
    result = bouzecode(["find the python files"], mock_llm=mock)
    outputs = [m["content"] for m in result.messages
               if m.get("role") == "tool" and m.get("name") == "Glob"]
    assert outputs, "no Glob tool result in the conversation"
    return outputs[0]


def _own_paths(out, root):
    """Paths printed by the Glob that belong to this test's own tree."""
    stem = root.as_posix().split("/")[-1]
    return [ln for ln in out.splitlines() if ln.endswith(".py") and stem in ln]


def test_wide_glob_returns_the_cap_and_reports_the_true_total(tmp_path):
    """252 matching files: the agent gets exactly GLOB_CAP paths and is told the true
    total, which adds up to what was shown plus what was hidden — no error, no refusal."""
    created = _tree(tmp_path, per_dir=84)
    out = _glob_result(tmp_path)

    banner = _TOTAL_RE.search(out)
    assert banner, out[-500:]
    total, shown = int(banner.group(1)), int(banner.group(2))
    hidden = int(_HIDDEN_RE.search(out).group(1))

    assert shown == GLOB_CAP
    assert len(_own_paths(out, tmp_path)) == GLOB_CAP   # the cap is what got printed
    assert total == shown + hidden                      # the total is fully accounted for
    assert total >= created                             # every file created was counted
    assert "Error" not in out
    assert "No files matched" not in out


def test_the_capped_result_still_says_where_the_hidden_files_are(tmp_path):
    """Orientation survives truncation: the directories holding the files that were
    NOT printed are listed with their counts, plus a ready-to-run narrower call."""
    _tree(tmp_path, per_dir=84)
    out = _glob_result(tmp_path)

    for directory in ("alpha", "beta", "gamma"):
        assert directory in out
    assert "paths not shown are in:" in out
    assert 'Refine: Glob(pattern="*.py"' in out


def test_a_glob_under_the_cap_is_returned_whole(tmp_path):
    """No cap banner and no missing path when the result already fits: the cap must
    not tax the well-scoped calls it is meant to leave alone."""
    _tree(tmp_path, per_dir=8)  # 24 files
    out = _glob_result(tmp_path).replace("\\", "/")

    assert _TOTAL_RE.search(out) is None
    for directory in ("alpha", "beta", "gamma"):
        for i in range(8):
            assert (tmp_path / directory / f"mod_{i:03d}.py").as_posix() in out
