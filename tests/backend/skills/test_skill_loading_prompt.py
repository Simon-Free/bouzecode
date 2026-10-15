# [desc] Tests that system prompt aggressively encourages skill loading [/desc]
"""Tests for skill loading encouragement in the system prompt."""


def test_get_skills_section_tells_to_load_skills_early():
    """The section pushes the model to open a skill BEFORE acting (see
    test_skills_section.py for the full contract)."""
    from bouzecode.backend.core.context import get_skills_section

    section = get_skills_section()
    assert "**AVANT** d'agir" in section
    assert "Skill(name=" in section


# NOTE: tests asserting a "Write/Edit BLOQUÉ before WritePlan" constraint were
# removed — that constraint no longer exists. The prompt now explicitly allows
# WritePlan + edits in the same turn (section 5), so the constraint is gone.
