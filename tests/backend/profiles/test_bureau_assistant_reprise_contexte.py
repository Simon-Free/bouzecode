"""After a /clear (fresh context) the bureau assistant must reload the Bureau state
(running tasks, what waits for the human) before answering."""
import unicodedata
from pathlib import Path

import pytest
import yaml

import bouzecode.backend.profiles as _profiles_pkg

BUILTIN = Path(_profiles_pkg.__file__).parent / "builtin"
MARKER = "contexte neuf"


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    return " ".join(text.encode("ascii", "ignore").decode().lower().split())


def _prompt(name: str) -> str:
    data = yaml.safe_load((BUILTIN / f"{name}.yaml").read_text(encoding="utf-8")) or {}
    return _norm(data.get("system_prompt_extra", ""))


def test_assistant_prompt_orders_reload_on_fresh_context():
    prose = _prompt("bureau-assistant")
    assert MARKER in prose
    assert "/clear" in prose
    assert "avant toute reponse" in prose
    for call in ("flotte()", 'taches(action="lister")', 'decisions(action="lister")'):
        assert call in prose, call


@pytest.mark.parametrize("name", sorted(p.stem for p in BUILTIN.glob("*.yaml")
                                        if p.stem != "bureau-assistant"))
def test_other_profiles_do_not_carry_the_reload_rule(name):
    assert MARKER not in _prompt(name)


def test_reload_tools_are_offered_to_assistant():
    from bouzecode.backend.tools.registration import tools_offered_to_profile
    offered = tools_offered_to_profile("bureau-assistant")
    assert {"Flotte", "Taches", "Decisions"} <= offered
