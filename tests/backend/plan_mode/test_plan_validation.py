# [desc] Tests that only the exact input "1" (with optional whitespace) is considered an approved plan response [/desc]
"""How a plan answer is read — deliberately unit level.

Approving a plan must be an unambiguous act: only the option number "1" counts.
Everything friendly-looking ("ok", "validé", "👍") must NOT start an
implementation the user did not really approve. The table of near-misses below is
the point of the test, and a conversation can only exercise one answer at a time,
so it stays a parametrised unit over the real is_plan_approved().
"""
import pytest
from bouzecode.backend.tools.plan_validation import is_plan_approved


@pytest.mark.parametrize("response", [
    "1",
    " 1 ",
    " 1",
    "1 ",
])
def test_only_the_option_number_one_approves_a_plan(response):
    """Typing the option number (with any surrounding spaces) approves the plan."""
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
def test_anything_else_leaves_the_plan_unapproved(response):
    """Any other answer — approval-sounding words included — is feedback, not a go."""
    assert is_plan_approved(response) is False
