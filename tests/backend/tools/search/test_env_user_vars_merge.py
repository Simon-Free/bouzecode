# [desc] Tests that registry user vars merge case-insensitively so the registry never shadows the in-process PATH. [/desc]
"""On Windows every Bash command is wrapped in `powershell -EncodedCommand …`.

The merged env passed to that subprocess used to add the registry `Path` next
to the process `PATH` as a SECOND, case-conflicting key. Under CreateProcess the
stale registry value then shadowed the repaired `PATH` — silently defeating the
PowerShell-on-PATH repair (and setx) and breaking every command with
`'powershell' n'est pas reconnu`. _merge_user_env merges case-insensitively.
"""
from __future__ import annotations

import os

from bouzecode.backend.tools.ops.shell_search import _merge_user_env

_PS = r"C:\Windows\System32\WindowsPowerShell\v1.0"


def test_registry_path_never_creates_a_case_conflicting_key():
    env = {"PATH": _PS + os.pathsep + r"C:\tools"}
    # Registry user 'Path' lacks the WindowsPowerShell dir (it lives in system PATH).
    merged = _merge_user_env(env, [("Path", r"C:\tools")])
    path_keys = [k for k in merged if k.lower() == "path"]
    assert path_keys == ["PATH"], f"case-duplicate key leaked: {path_keys}"
    assert "windowspowershell" in merged["PATH"].lower()


def test_genuinely_new_registry_path_entries_are_appended():
    merged = _merge_user_env({"PATH": r"C:\a;C:\b"}, [("Path", r"C:\b;C:\new")])
    assert merged["PATH"] == r"C:\a;C:\b;C:\new"  # C:\new appended once, C:\b not duplicated


def test_existing_var_is_not_overwritten_by_registry():
    merged = _merge_user_env({"FOO": "process"}, [("FOO", "registry"), ("foo", "alsoreg")])
    assert merged["FOO"] == "process"
    assert "foo" not in merged  # case-variant not added as a second key


def test_new_user_var_is_brought_in():
    merged = _merge_user_env({"PATH": "x"}, [("NEWVAR", "v")])
    assert merged["NEWVAR"] == "v"


def test_path_absent_from_process_env_takes_registry_value():
    merged = _merge_user_env({"FOO": "bar"}, [("Path", r"C:\fromreg")])
    assert merged["Path"] == r"C:\fromreg"
