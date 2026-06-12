# [desc] Tests that inline python -c commands are blocked by shell search while script execution is allowed
# <tool_use name="FinalAnswer" id="x1"><param name="answer">Tests that inline python -c commands are blocked by shell search while script execution is allowed</param></tool_use> [/desc]
from bouzecode.backend.tools.ops.shell_search import _bash, _BANNED_INLINE_RE


def test_python_c_simple_blocked():
    result = _bash('python -c "print(1)"')
    assert "BLOCKED" in result


def test_python3_c_blocked():
    result = _bash('python3 -c "print(1)"')
    assert "BLOCKED" in result


def test_py_c_blocked():
    result = _bash('py -c "print(1)"')
    assert "BLOCKED" in result


def test_python_c_with_pipe_blocked():
    result = _bash('echo x | python -c "import sys"')
    assert "BLOCKED" in result


def test_python_c_after_and_blocked():
    result = _bash('echo x && python -c "print(1)"')
    assert "BLOCKED" in result


def test_python_c_after_semicolon_blocked():
    result = _bash('cd /tmp ; python -c "print(1)"')
    assert "BLOCKED" in result


def test_blocked_message_suggests_write_pattern():
    result = _bash('python -c "print(1)"')
    assert "temp_" in result
    assert "Write" in result


def test_python_script_not_blocked():
    assert not _BANNED_INLINE_RE.search("python temp_check.py")


def test_python_dash_m_not_blocked():
    assert not _BANNED_INLINE_RE.search("python -m pytest")
