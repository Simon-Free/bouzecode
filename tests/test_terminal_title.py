import io
import os
import subprocess
import sys

import pytest

from bouzecode.ui import terminal_title as tt


class _Tty(io.StringIO):
    def isatty(self):
        return True


def test_icons_per_status():
    assert tt.build_title("running", "bouzecode") == "\u23f3 bouzecode"
    assert tt.build_title("done", "bouzecode") == "\u2705 bouzecode"
    assert tt.build_title("crashed", "bouzecode") == "\u274c bouzecode"
    assert tt.build_title("question", "bouzecode") == "\u2753 bouzecode"
    assert tt.build_title("idle", "bouzecode") == "bouzecode"


def test_writes_osc_sequence_on_tty(monkeypatch):
    monkeypatch.delenv("BOUZECODE_NO_TERMINAL_TITLE", raising=False)
    out = _Tty()
    assert tt.set_terminal_status("question", stream=out) is True
    value = out.getvalue()
    assert value.startswith("\x1b]0;\u2753 bouzecode") and value.endswith("\x07")
    assert tt.current_status() == "question"


def test_noop_when_not_tty(monkeypatch):
    monkeypatch.delenv("BOUZECODE_NO_TERMINAL_TITLE", raising=False)
    out = io.StringIO()
    assert tt.set_terminal_status("running", stream=out) is False
    assert out.getvalue() == ""


_CHILD = r'''
import ctypes, sys
from bouzecode.ui import terminal_title as tt
ok = tt.set_terminal_status("done")
buf = ctypes.create_unicode_buffer(512)
ctypes.windll.kernel32.GetConsoleTitleW(buf, 512)
with open(sys.argv[1], "w", encoding="utf-8") as fh:
    fh.write(f"{ok}\n{buf.value}")
'''


@pytest.mark.skipif(sys.platform != "win32", reason="Windows console only")
def test_real_windows_console_title_is_updated(tmp_path):
    """The OSC sequence must actually change a legacy console title.

    Without ENABLE_VIRTUAL_TERMINAL_PROCESSING the console silently ignores it.
    """
    script = tmp_path / "child.py"
    script.write_text(_CHILD, encoding="utf-8")
    out = tmp_path / "out.txt"
    env = {k: v for k, v in os.environ.items() if k != "BOUZECODE_NO_TERMINAL_TITLE"}
    # Import the code under test, not whatever the venv has installed.
    src = os.path.join(os.path.dirname(os.path.dirname(__file__)), "src")
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [src, env.get("PYTHONPATH")]))
    proc = subprocess.Popen(
        # Force the legacy conhost host (a bare new console may be delegated
        # to Windows Terminal, which always processes VT sequences).
        ["conhost.exe", sys.executable, str(script), str(out)],
        creationflags=subprocess.CREATE_NEW_CONSOLE,
        env=env,
    )
    assert proc.wait(timeout=60) == 0
    ok, title = out.read_text(encoding="utf-8").split("\n", 1)
    assert ok == "True"
    assert title.startswith("\u2705 bouzecode")


def test_enable_vt_is_noop_on_non_console_stream():
    assert tt._enable_vt(io.StringIO()) is False


def test_disabled_by_env(monkeypatch):
    monkeypatch.setenv("BOUZECODE_NO_TERMINAL_TITLE", "1")
    out = _Tty()
    assert tt.set_terminal_status("running", stream=out) is False
    assert out.getvalue() == ""
