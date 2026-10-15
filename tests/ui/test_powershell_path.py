# [desc] Tests that bouzecode locates PowerShell and repairs a PATH missing it on startup. [/desc]
"""On Windows every Bash command is wrapped in `powershell -EncodedCommand …`,
so a PATH stripped of the WindowsPowerShell directory breaks all shell commands.
_ensure_powershell_on_path repairs it in-process at startup."""
from __future__ import annotations

import os
import sys

import pytest

from bouzecode.ui.cli import (
    _find_powershell_dir, _ensure_powershell_on_path, _planned_user_path,
)

# Tout ce module décrit la réparation du PATH *Windows* (séparateur « ; », setx, dossiers
# WindowsPowerShell). Ailleurs, os.pathsep vaut « : » et ces décisions n'ont pas de sens.
pytestmark = pytest.mark.skipif(sys.platform != "win32",
                                reason="réparation du PATH PowerShell : Windows uniquement")


def test_find_powershell_dir_points_at_a_real_executable():
    directory = _find_powershell_dir()
    assert directory is not None
    assert (
        os.path.isfile(os.path.join(directory, "powershell.exe"))
        or os.path.isfile(os.path.join(directory, "pwsh.exe"))
    )


def test_ensure_is_noop_when_powershell_already_resolves():
    # On a healthy machine powershell is on PATH → no PATH mutation, no setx.
    import shutil
    if not shutil.which("powershell"):
        pytest.skip("powershell absent du PATH")
    before = os.environ["PATH"]
    _ensure_powershell_on_path()
    assert os.environ["PATH"] == before


# --- _planned_user_path: pure persistence decision (no setx side effects) ---

def test_planned_user_path_prepends_when_absent():
    assert _planned_user_path("C:\\ps", "C:\\a;C:\\b") == "C:\\ps;C:\\a;C:\\b"


def test_planned_user_path_skips_when_already_present():
    assert _planned_user_path("C:\\ps", "C:\\a;C:\\ps") is None
    # case-insensitive (Windows paths)
    assert _planned_user_path("C:\\PS", "c:\\ps;C:\\a") is None


def test_planned_user_path_handles_empty_user_path():
    assert _planned_user_path("C:\\ps", "") == "C:\\ps"


def test_planned_user_path_skips_when_result_would_truncate():
    long_path = ";".join(f"C:\\dir{i}" for i in range(200))
    assert len(long_path) > 1024
    assert _planned_user_path("C:\\ps", long_path) is None
