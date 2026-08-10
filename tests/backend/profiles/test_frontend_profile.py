"""Prove the built-in `frontend` profile loads, lists as a dispatch typology, and carries
its full 'quel test quand' doc + guardrails. No web server is started."""
from pathlib import Path

import yaml

_PROFILE = (
    Path(__file__).resolve().parents[3]
    / "src"
    / "bouzecode"
    / "backend"
    / "profiles"
    / "builtin"
    / "frontend.yaml"
)


def _profile_data() -> dict:
    return yaml.safe_load(_PROFILE.read_text(encoding="utf-8"))


def _system_prompt_extra() -> str:
    extra = _profile_data().get("system_prompt_extra", "")
    assert extra, "frontend.yaml has no system_prompt_extra"
    return extra


def test_frontend_yaml_is_a_system_profile():
    data = _profile_data()
    assert data["name"] == "frontend"
    assert data["kind"] == "system"
    # tools MUST be empty (full access) so dynamic MCP chrome-devtools tools are visible.
    assert data.get("tools") == [] or data.get("tools") is None


def test_frontend_is_registered_as_a_system_agent():
    from bouzecode.backend.profiles.discovery import load_system_profiles

    profiles = load_system_profiles()
    assert "frontend" in profiles, "frontend not returned by load_system_profiles()"
    assert profiles["frontend"].kind == "system"
    assert profiles["frontend"].tools == [], "frontend must have full tool access (tools=[])"


def test_frontend_is_a_selectable_dispatch_typology():
    from bouzecode.web_v2.services.typologies import get_typology, list_typologies

    names = {t["name"] for t in list_typologies()}
    assert "frontend" in names, "frontend not listed as a dispatch typology"
    typ = get_typology("frontend")
    assert typ is not None
    assert typ["profile"] == "frontend"


def test_frontend_prompt_documents_which_test_when():
    extra = _system_prompt_extra()
    # The three test levels must all be documented.
    assert "happy-dom" in extra
    assert "test_client" in extra
    assert "Playwright" in extra or "chrome-devtools" in extra
    # Explicit rule: happy-dom never for visual criteria.
    assert "happy-dom" in extra and "JAMAIS happy-dom" in extra


def test_frontend_prompt_has_guardrails():
    extra = _system_prompt_extra()
    # No invented fixtures; derive from real.
    assert "fixture inventée" in extra
    # Never run the web server in foreground.
    assert "FOREGROUND" in extra or "foreground" in extra
    # The render->screenshot->self-critique loop.
    assert "screenshot" in extra


def test_frontend_prompt_wires_chrome_devtools_flag():
    extra = _system_prompt_extra()
    assert "--enable-chrome-devtools" in extra
