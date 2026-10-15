# [desc] BashOutput(wait_s / until_exit): waits on a real background process instead of polling per turn. [/desc]
import sys
import time

import pytest

from bouzecode.backend.tools.ops.bash_bg import bash_output
from bouzecode.backend.tools.ops.bash_bg_wait import MAX_WAIT_S, borne_attente
from bouzecode.backend.tools.ops.shell_search import bash_handler

pytestmark = pytest.mark.skipif(
    sys.platform != "win32", reason="background commands are written in PowerShell"
)


def _start(command: str) -> str:
    started = bash_handler({"command": command, "background": True}, {})
    return started.split("bash_id=", 1)[1].split(" ", 1)[0]


def _timed_output(bash_id: str, **kwargs) -> tuple[str, float]:
    start = time.monotonic()
    result = bash_output(bash_id, **kwargs)
    return result, time.monotonic() - start


def test_returns_as_soon_as_output_arrives():
    bash_id = _start("Start-Sleep -Milliseconds 800; Write-Output HELLO; Start-Sleep 30")
    result, elapsed = _timed_output(bash_id, wait_s=20)
    bash_output(bash_id, kill=True)
    assert "[running]" in result
    assert "HELLO" in result
    assert elapsed < 5


def test_returns_when_process_exits():
    bash_id = _start("Start-Sleep -Milliseconds 800; exit 3")
    result, elapsed = _timed_output(bash_id, wait_s=20)
    assert "[exited code=3]" in result
    assert elapsed < 5


def test_gives_up_after_wait_s():
    bash_id = _start("Start-Sleep 30")
    result, elapsed = _timed_output(bash_id, wait_s=1)
    bash_output(bash_id, kill=True)
    assert "[running]" in result
    assert "attendu 1 s" in result
    assert 0.9 <= elapsed < 3


def test_without_wait_s_returns_immediately():
    bash_id = _start("Start-Sleep 30")
    result, elapsed = _timed_output(bash_id)
    bash_output(bash_id, kill=True)
    assert "[running]" in result
    assert elapsed < 0.5


def test_until_exit_skips_intermediate_output():
    bash_id = _start("Write-Output STEP1; Start-Sleep -Milliseconds 700; "
                     "Write-Output STEP2; Start-Sleep -Milliseconds 700; exit 0")
    result, elapsed = _timed_output(bash_id, wait_s=20, until_exit=True)
    assert "[exited code=0]" in result
    assert "STEP1" in result and "STEP2" in result
    assert elapsed < 5


def test_cancel_request_ends_the_wait():
    bash_id = _start("Start-Sleep 30")
    result, elapsed = _timed_output(bash_id, wait_s=20, cancelled=lambda: True)
    bash_output(bash_id, kill=True)
    assert "attente interrompue" in result
    assert elapsed < 1


def test_wait_bounds():
    assert borne_attente(None, False) == 0
    assert borne_attente(-5, False) == 0
    assert borne_attente("30", False) == 30
    assert borne_attente(10_000, False) == MAX_WAIT_S
    assert borne_attente(0, True) == MAX_WAIT_S
    assert borne_attente(12, True) == 12
