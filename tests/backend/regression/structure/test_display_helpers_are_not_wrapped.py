# [desc] info/ok/warn/err print and return None, so wrapping them in print() emits a bare "None" line. [/desc]
"""The stray `None` between `Active: ...` and the REPL prompt.

`ui/ansi.py` defines `info(msg)` as `print(clr(msg, "cyan"))`: it prints and
returns None. `print(info("Active: ..."))` therefore printed the line, then
printed `None` underneath. Three call sites did it. This test states the rule
for the whole tree rather than for the one banner that was noticed.
"""
from __future__ import annotations

import re
from pathlib import Path

from bouzecode.ui.ansi import err, info, ok, warn

_SRC_ROOT = Path(__file__).resolve().parents[4] / "src"
_HELPERS = ("info", "ok", "warn", "err")
_WRAPPED = re.compile(r"\bprint\(\s*(?:" + "|".join(_HELPERS) + r")\(")


def test_the_helpers_return_nothing(capsys):
    assert [f("x") for f in (info, ok, warn, err)] == [None, None, None, None]
    assert capsys.readouterr().out != ""


def test_no_source_file_wraps_a_display_helper_in_print():
    offenders = []
    for path in _SRC_ROOT.rglob("*.py"):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if _WRAPPED.search(line):
                offenders.append(f"{path.relative_to(_SRC_ROOT)}:{number}")

    assert offenders == [], (
        "these call sites print the helper's return value (None) on its own line: "
        + ", ".join(offenders)
    )
