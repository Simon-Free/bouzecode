# [desc] Tests for win32 .ps1 spill (no command-length limit) and Bash background exec + BashOutput. [/desc]
import base64
import sys
import time
from pathlib import Path

import pytest

from bouzecode.backend.tools.ops.shell_search import (
    _build_popen_command, _bash, bash_handler,
)
from bouzecode.backend.tools.ops.bash_bg import bash_output

pytestmark = pytest.mark.skipif(
    sys.platform != "win32", reason="PowerShell EncodedCommand / .ps1 spill is win32-only"
)


def _poll_until(bash_id, needle, tries=40, delay=0.2):
    """Poll BashOutput until `needle` appears, accumulating output. Returns all text."""
    seen = ""
    for _ in range(tries):
        seen += bash_output(bash_id)
        if needle in seen:
            return seen
        time.sleep(delay)
    return seen


def test_small_command_encoded_inline_no_spill():
    argv, shell, temp = _build_popen_command("Write-Output hi")
    assert temp is None
    assert shell is False
    assert argv[-2] == "-EncodedCommand"
    assert "powershell" in argv[0].lower()
    assert "-NoProfile" in argv  # le profil utilisateur : ~150 ms par commande, rien d'utile


def test_large_command_spills_to_bom_ps1_and_stub_launches_it():
    big = "Write-Output 'STARTMARK'\n" + "\n".join(
        f"$var_{i} = {i}" for i in range(800)
    ) + "\nWrite-Output 'ENDMARK'"
    argv, shell, temp = _build_popen_command(big)
    try:
        assert temp is not None and temp.endswith(".ps1")
        raw = Path(temp).read_bytes()
        assert raw[:3] == b"\xef\xbb\xbf"  # UTF-8 BOM so PS 5.1 doesn't read it as ANSI
        assert "STARTMARK" in raw.decode("utf-8-sig")
        # the encoded payload is the tiny stub that launches the file, not the body
        stub = base64.b64decode(argv[-1]).decode("utf-16-le")
        assert stub.startswith("& '") and temp in stub
    finally:
        Path(temp).unlink(missing_ok=True)


def test_large_multiline_command_executes_via_spill():
    big = "Write-Output 'STARTMARK'\n" + "\n".join(
        f"$var_{i} = {i}" for i in range(800)
    ) + "\nWrite-Output 'ENDMARK'"
    result = _bash(big)
    assert "STARTMARK" in result
    assert "ENDMARK" in result


def test_background_polls_running_then_kill():
    started = bash_handler(
        {"command": "Write-Output READY; Start-Sleep 30", "background": True}, {}
    )
    assert "bash_id=" in started
    bash_id = started.split("bash_id=", 1)[1].split(" ", 1)[0]

    seen = _poll_until(bash_id, "READY")
    assert "READY" in seen
    assert "[running]" in bash_output(bash_id)

    killed = bash_output(bash_id, kill=True)
    assert "[killed]" in killed
    # registry cleared after kill
    assert "unknown bash_id" in bash_output(bash_id)


def test_background_reports_exit_code_and_output():
    started = bash_handler(
        {"command": "Write-Output DONE", "background": True}, {}
    )
    bash_id = started.split("bash_id=", 1)[1].split(" ", 1)[0]
    seen = _poll_until(bash_id, "exited code=0")
    assert "DONE" in seen
    assert "exited code=0" in seen


def test_background_runs_a_temp_file_addressed_by_its_logical_path():
    """Write(temp=True) promises Bash substitutes the logical path by the real one.
    Measured on agent b63d21ce5b09 (2026-08-27): background=true did NOT substitute,
    so the script it had just written 'did not exist' and the agent slept 240 s for a
    `No such file or directory`. The promise must hold on the background path too."""
    from bouzecode.backend.tools.ops.scratch import resolve_scratch_path

    logical = str(Path.home() / ".bouzecode" / "tmp" / "bg_scratch_probe.py")
    real = resolve_scratch_path(logical)
    real.write_text("print('SCRATCH_BG_MARKER')\n", encoding="utf-8")
    try:
        started = bash_handler(
            {"command": f'& "{sys.executable}" "{logical}"', "background": True}, {}
        )
        bash_id = started.split("bash_id=", 1)[1].split(" ", 1)[0]
        seen = _poll_until(bash_id, "exited code=")
        assert "SCRATCH_BG_MARKER" in seen, seen
        assert "No such file" not in seen, seen
    finally:
        real.unlink(missing_ok=True)


def test_background_output_is_plain_text_not_raw_clixml():
    """A background PowerShell job serializes secondary streams as a `#< CLIXML`
    envelope. Returned raw, the useful error drowns in XML with `_x000D__x000A_`
    escapes: unreadable for the agent and it defeats every grep-based supervision."""
    payload_head = "#< CLIXML"
    payload_body = (
        '<Objs Version="1.1.0.1" xmlns="http://schemas.microsoft.com/powershell/2004/04">'
        '<Obj S="progress" RefId="0"><MS><PR N="Record">'
        '<AV>Preparation des modules a la premiere utilisation.</AV></PR></MS></Obj>'
        '<S S="Error">uv : cannot open file recompute.py_x000D__x000A_</S>'
        '</Objs>'
    )
    started = bash_handler({
        "command": f"Write-Output '{payload_head}'; Write-Output '{payload_body}'",
        "background": True,
    }, {})
    bash_id = started.split("bash_id=", 1)[1].split(" ", 1)[0]
    seen = _poll_until(bash_id, "exited code=")
    assert "uv : cannot open file recompute.py" in seen, seen
    assert "#< CLIXML" not in seen, seen
    assert "_x000D_" not in seen, seen
    assert "Preparation" not in seen, seen
