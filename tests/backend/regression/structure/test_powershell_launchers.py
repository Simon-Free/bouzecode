# [desc] The .ps1 launchers stay pure ASCII and load .env before installing anything. [/desc]
"""Two things a first install got wrong.

Encoding: Windows PowerShell 5.1 re-reads a BOM-less `.ps1` as ANSI, so the web
launcher's banner printed as `=== Bouz?GUI ===`. The project's answer is pure
ASCII in every `.ps1` — no accent, no em dash, no box character.

Ordering: every launcher installed dependencies BEFORE loading `.env`, so the
proxy variables documented for a corporate network could not reach the package
index. On such a network there was no way to bootstrap at all.
"""
from __future__ import annotations

from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[4]
_LAUNCHERS = sorted(_REPO_ROOT.glob("*.ps1"))
# The launchers that install Python dependencies, i.e. that reach the index.
_INSTALLERS = ("bouzecode.ps1", "bouzegui.ps1", "bouzecode_self_update.ps1")


def test_the_repo_actually_ships_launchers():
    assert [p.name for p in _LAUNCHERS], "no .ps1 found at the repo root"


@pytest.mark.parametrize("launcher", _LAUNCHERS, ids=lambda p: p.name)
def test_launcher_is_pure_ascii(launcher):
    raw = launcher.read_bytes()
    offenders = [(i, hex(b)) for i, b in enumerate(raw) if b > 127]

    assert offenders == [], (
        f"{launcher.name} carries non-ASCII bytes at {offenders[:5]}; "
        "PowerShell 5.1 reads a BOM-less .ps1 as ANSI and mangles them"
    )


def _first_line_with(text: str, needle: str) -> int:
    """Index of the first CODE line containing `needle` (comments skipped), or -1."""
    for number, line in enumerate(text.splitlines()):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if needle in stripped:
            return number
    return -1


@pytest.mark.parametrize("name", _INSTALLERS)
def test_dotenv_is_loaded_before_dependencies_are_installed(name):
    text = (_REPO_ROOT / name).read_text(encoding="ascii")
    load_at = _first_line_with(text, "Import-DotEnv")
    install_at = _first_line_with(text, "pip install")

    assert load_at != -1, f"{name} never loads .env"
    assert install_at != -1, f"{name} was expected to install dependencies"
    assert load_at < install_at, (
        f"{name} installs before loading .env: the proxy settings it documents "
        "cannot reach the package index"
    )
