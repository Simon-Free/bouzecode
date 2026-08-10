# [desc] Tests the static skills section: SkillList discovery, Skill loading, LoadProjectConfig rule. [/desc]
"""get_skills_section() contract since the prompt V2 redesign (4235c23/dc56090):
skills are no longer LISTED in the system prompt — the model discovers them via
SkillList() and loads them via Skill(name=...). The section is a short static
instruction; per-skill content moved behind the tools."""

from bouzecode.backend.core.context import get_skills_section


def test_skills_section_teaches_discovery_via_skilllist():
    section = get_skills_section()
    assert "SkillList()" in section
    assert "Skill(name=" in section


def test_skills_section_teaches_load_before_acting():
    """Loading after acting is too late — the instruction must say BEFORE."""
    section = get_skills_section()
    assert "BEFORE" in section


def test_skills_section_keeps_load_project_config_rule():
    """Project-specific skills still require LoadProjectConfig first."""
    section = get_skills_section()
    assert "LoadProjectConfig" in section


def test_skills_section_is_static_no_skill_listing():
    """The section must not embed a skill list (it would bust the prompt cache
    and re-grow the prompt the V2 redesign shrank)."""
    section = get_skills_section()
    assert "- **" not in section, "per-skill bullet listing reintroduced?"
    assert section == get_skills_section(), "section must be deterministic/static"
