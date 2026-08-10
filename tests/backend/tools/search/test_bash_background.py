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
