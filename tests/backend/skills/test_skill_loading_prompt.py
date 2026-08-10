# [desc] Tests that system prompt aggressively encourages skill loading and thinking prompt includes skill scanning rule [/desc]
"""Tests for skill loading encouragement in the system prompt."""
from pathlib import Path


def test_get_skills_section_encourages_aggressive_loading():
    """Prompt V2: the section is a short static instruction (SkillList/Skill
    discovery — see test_skills_section.py for the full contract); it must still
    push the model to load skills liberally and early."""
    from bouzecode.backend.core.context import get_skills_section

    section = get_skills_section()
    assert "too many skills than too few" in section
    assert "Skill(name=" in section


def test_thinking_prompt_contains_skill_scanning_rule():
    """Verify the thinking prompt includes a rule about scanning skills."""
    prompts_dir = Path(__file__).resolve().parents[3] / "src" / "system_prompts"
    content = (prompts_dir / "02_think_out_loud.txt").read_text(encoding="utf-8")
    # Should contain a rule about scanning skills
    assert "Scanner les Skills" in content
    # Should mention Skill(name=...)
    assert "Skill(name=" in content
    # Should be in the numbered rules section
    assert "7." in content

# NOTE: tests asserting a "Write/Edit BLOQUÉ before WritePlan" constraint were
# removed — that constraint no longer exists. The prompt now explicitly allows
# WritePlan + edits in the same turn (section 5), so the constraint is gone.
