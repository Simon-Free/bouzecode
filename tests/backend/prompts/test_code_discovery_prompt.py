# [desc] Tests that code discovery guidance lives in the default code-agent profile. [/desc]
"""Code discovery guidance now lives in the default (code) agent profile, layered on
the agnostic noyau at depth 0 by dispatch — not in the shared base prompt."""

from pathlib import Path

from bouzecode.backend.core.context import build_system_prompt
from bouzecode.backend.profiles import load_profiles_from_dir


def test_code_discovery_guidance_in_default_profile():
    repo_root = Path(__file__).resolve().parents[3]
    extra = load_profiles_from_dir(repo_root / ".bouzecode" / "profiles")["default"].system_prompt_extra
    assert "Découverte de code" in extra or "code discovery" in extra.lower()
    # L'échelle ne cite QUE des outils réellement offerts : GetFolderDescription en a été
    # retiré (obsolète, zéro appel en 17 897 tours) — cf. test_prompt_registry_conformity.
    assert "GetFolderDescription" not in extra
    assert "Glob" in extra
    assert "Grep" in extra
    assert "Read(symbol=" in extra
    # Separation of concerns: not in the agnostic noyau.
    assert "Read(symbol=" not in build_system_prompt({})
