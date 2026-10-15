"""An inherited PYTHONHOME must never reach a child process.

bouzecode is usually started by uv or an IDE, which leaks ITS OWN PYTHONHOME
(uv's cpython-3.12) into the process env. Every shell command then runs the
python.exe found on PATH (3.13) against a 3.12 stdlib and dies on the first
`import re` with `AssertionError: SRE module mismatch`.
"""
from bouzecode.backend.tools.ops import shell_env, test_runner

UV_HOME = r"C:\Users\x\AppData\Roaming\uv\python\cpython-3.12-windows-x86_64-none"


def test_strip_removes_pythonhome_and_keeps_everything_else():
    env = {"PATH": "C:\\Windows", "PYTHONHOME": UV_HOME, "PYTHONPATH": "C:\\lib"}

    cleaned = shell_env.strip_inherited_python_home(env)

    assert "PYTHONHOME" not in cleaned
    assert cleaned["PATH"] == "C:\\Windows"
    # PYTHONPATH only ADDS search paths, it never overrides the stdlib: keep it.
    assert cleaned["PYTHONPATH"] == "C:\\lib"


def test_strip_is_case_insensitive():
    # Windows env var names are case-insensitive, so a dict key may be any case.
    cleaned = shell_env.strip_inherited_python_home({"Pythonhome": UV_HOME, "A": "1"})

    assert list(cleaned) == ["A"]


def test_bash_env_has_no_pythonhome(monkeypatch):
    monkeypatch.setenv("PYTHONHOME", UV_HOME)
    shell_env._get_env_with_user_vars.cache_clear()
    try:
        env = shell_env._get_env_with_user_vars()
    finally:
        shell_env._get_env_with_user_vars.cache_clear()

    assert not [k for k in env if k.lower() == "pythonhome"]


def test_pytest_runner_env_has_no_pythonhome(monkeypatch):
    monkeypatch.setenv("PYTHONHOME", UV_HOME)

    env = test_runner._get_base_env()

    assert not [k for k in env if k.lower() == "pythonhome"]
