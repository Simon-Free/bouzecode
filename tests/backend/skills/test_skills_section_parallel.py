"""The skills section must push the agent to search skills alongside code exploration,
and to capitalise costly findings into a project skill on its own."""

from bouzecode.backend.core.context import get_skills_section


def test_skill_research_runs_in_parallel_with_code_search():
    section = get_skills_section()
    assert "même lot" in section
    assert "langage naturel" in section
    assert "sessions précédentes" in section
    for tool in ("FindCode", "Grep"):
        assert tool in section


def test_costly_findings_are_capitalised_autonomously():
    section = get_skills_section()
    assert "skill projet" in section
    assert "sans demander" in section
