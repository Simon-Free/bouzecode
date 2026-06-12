# [desc] Tests that only the exact response "1" (with optional whitespace) is accepted as plan approval
# <tool_use name="FinalAnswer" id="x1"><param name="answer">Tests that only the exact response "1" (with optional whitespace) is accepted as plan approval</param></tool_use> [/desc]
import pytest
from bouzecode.backend.tools.plan_validation import is_plan_approved


@pytest.mark.parametrize("response", [
    "1",
    " 1 ",
    " 1",
    "1 ",
])
def test_approved(response):
    assert is_plan_approved(response) is True


@pytest.mark.parametrize("response", [
    "oui",
    "yes",
    "ok",
    "go",
    "2",
    "0",
    "non",
    "no",
    "",
    "lgtm",
    "d'accord",
    "parfait",
    "c'est bon",
    "ça part",
    "validé",
    "approve",
    "je veux changer le nom de la variable",
    "ajoute un test pour le cas null",
    "👍",
    "11",
    "1a",
    " ",
])
def test_rejected(response):
    assert is_plan_approved(response) is False
