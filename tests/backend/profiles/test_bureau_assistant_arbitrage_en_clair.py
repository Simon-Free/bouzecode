"""When the bureau assistant needs a decision from the human, it must state the question
in clear text in the chat (question, context, options) instead of pointing to a draft/card."""
import unicodedata
from pathlib import Path

import pytest
import yaml

import bouzecode.backend.profiles as _profiles_pkg

BUILTIN = Path(_profiles_pkg.__file__).parent / "builtin"
MARKER = "question en clair"


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    return " ".join(text.encode("ascii", "ignore").decode().lower().split())


def _prompt(name: str) -> str:
    data = yaml.safe_load((BUILTIN / f"{name}.yaml").read_text(encoding="utf-8")) or {}
    return _norm(data.get("system_prompt_extra", ""))


def test_assistant_prompt_requires_clear_arbitration_question():
    prose = _prompt("bureau-assistant")
    assert MARKER in prose
    # the three required parts of an arbitration request
    for part in ("la question en une phrase", "contexte", "tache `id` + titre",
                 "ticket", "agent", "source", "les options", "consequence"):
        assert part in prose, part
    # applies to relayed agent questions and decision cards too
    assert "question d'agent a relayer" in prose
    assert "carte de decision" in prose
    # a draft / card / id never replaces the text
    assert "ne remplacent jamais ce texte" in prose


def test_assistant_prompt_requires_full_question_and_no_generic_message():
    prose = _prompt("bureau-assistant")
    # full text of an agent question, not only its id
    assert "texte complet, pas seulement son id" in prose
    # what was measured and why the decision is needed
    assert "ce qui a ete mesure" in prose
    assert "pourquoi la decision est necessaire" in prose
    # options shown without deciding for the human
    assert "sans trancher a la place de l'humain" in prose
    # a generic "a decision is waiting" message is not enough
    assert "message generique" in prose
    assert "une decision attend ta reponse" in prose


@pytest.mark.parametrize("name", sorted(p.stem for p in BUILTIN.glob("*.yaml")
                                        if p.stem != "bureau-assistant"))
def test_other_profiles_do_not_carry_the_arbitration_rule(name):
    assert MARKER not in _prompt(name)
