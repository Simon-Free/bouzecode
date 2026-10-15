# [desc] Tests the static skills section: SkillResearch discovery, Skill loading, LoadProjectConfig rule. [/desc]
"""get_skills_section() contract since the prompt V2 redesign (4235c23/dc56090):
skills are no longer LISTED in the system prompt — the model finds them by keyword via
SkillResearch(query=...) and loads them via Skill(name=...). The section is a short static
instruction; per-skill content moved behind the tools."""

from bouzecode.backend.core.context import get_skills_section


def test_skills_section_teaches_discovery_via_skill_research():
    section = get_skills_section()
    assert "SkillResearch(query=" in section
    assert "SkillList" not in section
    assert "Skill(name=" in section


def test_skills_section_teaches_load_before_acting():
    """Loading after acting is too late — the instruction must say BEFORE."""
    section = get_skills_section()
    assert "**AVANT** d'agir" in section


def test_skills_section_keeps_load_project_config_rule():
    """Project-specific skills still require LoadProjectConfig first."""
    section = get_skills_section()
    assert "LoadProjectConfig" in section


def test_skills_section_is_static_no_skill_listing():
    """The section must not embed a skill list (it would bust the prompt cache
    and re-grow the prompt the V2 redesign shrank)."""
    from bouzecode.backend.tools.skill.loader import load_skills

    section = get_skills_section()
    listed = [s.name for s in load_skills() if f"`{s.name}`" in section or f"**{s.name}**" in section]
    assert listed == [], f"per-skill listing reintroduced: {listed}"
    assert section == get_skills_section(), "section must be deterministic/static"
