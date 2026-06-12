# [desc] Tests CLIXML stderr stripping logic for PowerShell noise removal and real error preservation [/desc]
"""CLIXML stderr stripping.

On Windows, PowerShell serializes a native exe's secondary streams as a
`#< CLIXML` `<Objs>...</Objs>` envelope. Module-load progress records are pure
noise that polluted every Bash result (and misled the model into thinking real
output was "garbage"). We drop the envelope but recover genuine `<S>` stderr.
"""
from __future__ import annotations

from bouzecode.backend.tools.ops.shell_search import _strip_clixml

# Real progress-only noise captured from session_112830 (mojibake preserved).
_PROGRESS_NOISE = (
    '#< CLIXML\n'
    '<Objs Version="1.1.0.1" xmlns="http://schemas.microsoft.com/powershell/2004/04">'
    '<Obj S="progress" RefId="0"><TN RefId="0"><T>System.Management.Automation.PSCustomObject</T>'
    '<T>System.Object</T></TN><MS><I64 N="SourceId">1</I64><PR N="Record">'
    '<AV>Preparation des modules a la premiere utilisation.</AV><AI>0</AI><Nil />'
    '<PI>-1</PI><PC>-1</PC><T>Completed</T><SR>-1</SR><SD> </SD></PR></MS></Obj></Objs>'
)


def test_pure_progress_noise_is_fully_stripped():
    assert _strip_clixml(_PROGRESS_NOISE) == ""


def test_non_clixml_stderr_is_untouched():
    plain = "Traceback (most recent call last):\n  File x\nValueError: boom"
    assert _strip_clixml(plain) == plain


def test_real_error_lines_survive_inside_clixml():
    stderr = (
        '#< CLIXML\n'
        '<Objs Version="1.1.0.1" xmlns="http://schemas.microsoft.com/powershell/2004/04">'
        '<Obj S="progress"><MS><PR N="Record"><AV>Preparation</AV></PR></MS></Obj>'
        '<S S="Error">error: cannot find module foo</S>'
        '<S S="Error">exit code 1</S>'
        '</Objs>'
    )
    out = _strip_clixml(stderr)
    assert "Preparation" not in out
    assert "error: cannot find module foo" in out
    assert "exit code 1" in out


def test_clixml_escapes_are_decoded():
    stderr = '#< CLIXML\n<Objs><S S="Error">a _x003C_tag_x003E_ &amp; b</S></Objs>'
    out = _strip_clixml(stderr)
    assert out == "a <tag> & b"
